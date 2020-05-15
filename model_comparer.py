import argparse
import os

from torch.optim.lr_scheduler import LambdaLR

from dataloader import dataloader
from model.config import cfg
from model.model import GSCAN_model
from model.utils import *

model_file = "output_model/model_best.pth.tar"
baseline_file = "output_model/model_best.pth.tar"

def exact_match_indicator(data_iterator, model, max_decoding_steps, pad_idx, sos_idx, eos_idx,
                max_examples_to_evaluate=None):  # \TODO evaluate function might be broken now. This is Ruis' code.
    exact_match_terms = []
    with torch.no_grad():
        for batch, output_sequence, target_sequence, _, _, aux_acc_target in predict(
                data_iterator=data_iterator, model=model, max_decoding_steps=max_decoding_steps, pad_idx=pad_idx,
                sos_idx=sos_idx, eos_idx=eos_idx, max_examples_to_evaluate=max_examples_to_evaluate):
            seq_eq = torch.eq(output_sequence, target_sequence)
            mask = torch.eq(target_sequence, pad_idx) + torch.eq(target_sequence, sos_idx)
            seq_eq.masked_fill_(mask, 0)
            total = (~mask).sum(-1).float()
            accuracy = seq_eq.sum(-1) / total
            exact_match_terms.append(accuracy.eq(1.).data.numpy())
    return torch.cat(exact_match_terms, dim=0)

def predict_and_write(data_iterator, model, example_indicator, max_decoding_steps, vocab,
                      max_examples_to_evaluate=None, out='predict.json'):
    # example_indicator: [datasetsize,] bool tensor indicating which example should be saved
    indicator_idx = 0
    pad_idx, sos_idx, eos_idx = vocab.stoi['<pad>'], vocab.stoi['<sos>'], \
                                vocab.stoi['<eos>']
    predict_output = []
    with torch.no_grad():
        for batch, output_sequence, target_sequence, attention_weights_commands, attention_weights_situations, \
            aux_acc_target in predict(data_iterator=data_iterator, model=model, max_decoding_steps=max_decoding_steps,
                                      pad_idx=pad_idx, sos_idx=sos_idx, eos_idx=eos_idx,
                                      max_examples_to_evaluate=max_examples_to_evaluate):
            # output_sequence: bs x max_decoding_steps
            batchsize = batch.situation.shape[0]
            batch_indicator = example_indicator[indicator_idx:indicator_idx+batchsize]
            indicator_idx += batchsize
            if batch_indicator.sum() == 0:
                continue
            select_and_convert = lambda x: torch.masked_select(x, batch_indicator).cpu().numpy().astype(int)

            selected_input = select_and_convert(batch.input)
            input_tokens = translate_sequence(selected_input, vocab.itos, eos_idx)

            selected_output = select_and_convert(output_sequence)
            output_tokens = translate_sequence(selected_output, vocab.itos, eos_idx)

            selected_target = select_and_convert(target_sequence)
            target_tokens = translate_sequence(selected_target, vocab.itos, eos_idx)

            selected_situation = select_and_convert(batch.situation).tolist()

            predict_output.append({"input": input_tokens, "prediction": output_tokens,
                           "target": target_tokens, "situation": selected_situation,
                           "attention_weights_input": attention_weights_commands,
                           "attention_weights_situation": attention_weights_situations})
    with open(out, 'w') as f:
        json.dump(predict_output, f)


# import models
def evaluate(data_iterator, model, max_decoding_steps, pad_idx, sos_idx, eos_idx, max_examples_to_evaluate=None):  # \TODO evaluate function might be broken now. This is Ruis' code.
    target_accuracies = []
    exact_match = 0
    num_examples = 0
    correct_terms = 0
    total_terms = 0
    for input_sequence, output_sequence, target_sequence, _, _, aux_acc_target in predict(
            data_iterator=data_iterator, model=model, max_decoding_steps=max_decoding_steps, pad_idx=pad_idx,
            sos_idx=sos_idx, eos_idx=eos_idx, max_examples_to_evaluate=max_examples_to_evaluate):
        # accuracy = sequence_accuracy(output_sequence, target_sequence[0].tolist()[1:-1])
        # accuracy = sequence_accuracy(output_sequence, target_sequence)
        num_examples += output_sequence.shape[0]
        seq_eq = torch.eq(output_sequence, target_sequence)
        mask = torch.eq(target_sequence, pad_idx) + torch.eq(target_sequence, sos_idx)
               # torch.eq(target_sequence, eos_idx)
        seq_eq.masked_fill_(mask, 0)
        total = (~mask).sum(-1).float()
        accuracy = seq_eq.sum(-1) / total
        total_terms += total.sum().data.item()
        correct_terms += seq_eq.sum().data.item()
        exact_match += accuracy.eq(1.).sum().data.item()
        target_accuracies.append(aux_acc_target)
    return (float(correct_terms) / total_terms) * 100, (exact_match / num_examples) * 100, \
            float(np.mean(np.array(target_accuracies))) * 100


def train(train_data_path: str, val_data_paths: dict, use_cuda: bool):
    device = torch.device(type='cuda') if use_cuda else torch.device(type='cpu')

    logger.info("Loading Training set...")
    logger.info(cfg.MODEL_NAME)
    train_iter, train_input_vocab, train_target_vocab = dataloader(train_data_path,
                                                                   batch_size=cfg.TRAIN.BATCH_SIZE,
                                                                   use_cuda=use_cuda)  # \TODO add k and statistics and shuffling
    val_iters = {}
    for split_name, path in val_data_paths.items():
        val_iters[split_name], _, _ = dataloader(path, batch_size=cfg.VAL_BATCH_SIZE, use_cuda=use_cuda,
                                input_vocab=train_input_vocab, target_vocab=train_target_vocab, random_shuffle=False)

    pad_idx, sos_idx, eos_idx = train_target_vocab.stoi['<pad>'], train_target_vocab.stoi['<sos>'], \
                                train_target_vocab.stoi['<eos>']

    train_input_vocab_size, train_target_vocab_size = len(train_input_vocab.itos), len(train_target_vocab.itos)


    logger.info("Loading Dev. set...")

    val_input_vocab_size, val_target_vocab_size = train_input_vocab_size, train_target_vocab_size
    logger.info("Done Loading Dev. set.")

    model = GSCAN_model(pad_idx, eos_idx, train_input_vocab_size, train_target_vocab_size, is_baseline=False)
    model = model.cuda() if use_cuda else model
    assert os.path.isfile(model_file), "No model checkpoint found at {}".format(model_file)
    logger.info("Loading model checkpoint from file at '{}'".format(model_file))
    _ = model.load_model(model_file)

    baseline = GSCAN_model(pad_idx, eos_idx, train_input_vocab_size, train_target_vocab_size, is_baseline=True)
    baseline = baseline.cuda() if use_cuda else baseline
    assert os.path.isfile(baseline_file), "No baseline checkpoint found at {}".format(baseline_file)
    logger.info("Loading model checkpoint from file at '{}'".format(baseline_file))
    _ = baseline.load_model(baseline_file)

    with torch.no_grad():
        model.eval()
        logger.info("Evaluating..")
        print(val_iters)
        for split_name, val_iter in val_iters.items():
            model_exact_match = exact_match_indicator(
                val_iter, model=model,
                max_decoding_steps=30, pad_idx=pad_idx,
                sos_idx=sos_idx,
                eos_idx=eos_idx,
                max_examples_to_evaluate=None)
            baseline_exact_match = exact_match_indicator(
                val_iter, model=baseline,
                max_decoding_steps=30, pad_idx=pad_idx,
                sos_idx=sos_idx,
                eos_idx=eos_idx,
                max_examples_to_evaluate=None)
            model_diff = torch.bitwise_xor(model_exact_match, baseline_exact_match)
            model_better_exs = torch.bitwise_and(model_diff, model_exact_match)
            predict_and_write(val_iter, baseline, model_better_exs, 30, train_input_vocab, out=split_name + '_predict.json')




def main(flags, use_cuda):

    if not os.path.exists(cfg.OUTPUT_DIRECTORY):
        os.mkdir(os.path.join(os.getcwd(), cfg.OUTPUT_DIRECTORY))

    train_data_path = os.path.join(cfg.DATA_DIRECTORY, "train.json")

    test_splits = [
        'situational_1',
        'situational_2',
        'test',
        'visual',
        'visual_easier',
        'dev',
        'adverb_1',
        'adverb_2',
        'contextual',
    ]
    val_data_paths = {split_name: os.path.join(cfg.DATA_DIRECTORY, split_name + '.json') for split_name in test_splits}  # \TODO val dataset not exist

    if cfg.MODE == "train":
        train(train_data_path=train_data_path, val_data_paths=val_data_paths, use_cuda=use_cuda)

    elif cfg.MODE == "predict":
        raise NotImplementedError()

    else:
        raise ValueError("Wrong value for parameters --mode ({}).".format(cfg.MODE))


if __name__ == "__main__":
    # torch.manual_seed(cfg.SEED)
    FORMAT = "%(asctime)-15s %(message)s"
    logging.basicConfig(format=FORMAT, level=logging.DEBUG,
                        datefmt="%Y-%m-%d %H:%M")
    logger = logging.getLogger(__name__)
    use_cuda = True if torch.cuda.is_available() else False
    logger.info("Initialize logger")

    if use_cuda:
        logger.info("Using CUDA.")
        logger.info("Cuda version: {}".format(torch.version.cuda))

    parser = argparse.ArgumentParser(description="LGCN models for GSCAN")
    # \TODO merge args into config. See Ronghang's code.
    args = parser.parse_args()

    main(args, use_cuda)