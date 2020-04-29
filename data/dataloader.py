import torch
import torchtext as tt
import torchtext.data as data


def dataloader(data_path, batch_size=32, device=torch.device('cpu'), fix_length=None, input_vocab=None, target_vocab=None):
    INPUT_FIELD = tt.data.Field(sequential=True, include_lengths=True, batch_first=True, fix_length=fix_length)
    TARGET_FIELD = tt.data.Field(sequential=True, include_lengths=True, batch_first=True, is_target=True,
                                 fix_length=fix_length)
    SITUATION_FIELD = tt.data.RawField(postprocessing=lambda x: torch.FloatTensor(x)) if device == torch.device('cpu') \
        else tt.data.RawField(postprocessing=lambda x: torch.cuda.FloatTensor(x))
    dataset = tt.data.TabularDataset(path=data_path, format="json",
                                     fields={'input': ('input', INPUT_FIELD),
                                             'target': ('target', TARGET_FIELD),
                                             'situation': ('situation', SITUATION_FIELD)}
                                     )
    if input_vocab is None:
        INPUT_FIELD.build_vocab(dataset)
    else:
        INPUT_FIELD.vocab = input_vocab
    if target_vocab is None:
        TARGET_FIELD.build_vocab(dataset)
    else:
        TARGET_FIELD.vocab = target_vocab
    iterator = tt.data.Iterator(dataset, batch_size=batch_size)
    return iterator, INPUT_FIELD.vocab, TARGET_FIELD.vocab


if __name__ == '__main__':

    train_iter, input_vocab, target_vocab = dataloader('train.json')
    dev_iter, _, _ = dataloader('dev.json', input_vocab=input_vocab, target_vocab=target_vocab)
    # %%
    for x in train_iter:
        print(x.target)
        print(x.input)
        print(x.situation)
        print(input_vocab.stoi)
        print(input_vocab.itos)
        break