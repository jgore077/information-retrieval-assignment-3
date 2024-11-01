# -*- coding: utf-8 -*-
"""SBERT-CrossEncoder.ipynb

Automatically generated by Colab.

Original file is located at
    https://colab.research.google.com/drive/1ZAnXpfn_myQEyHSrvFGKTAyhEazBo3Di
"""

from BiWrapper import remove_html_tags

TRAIN_FILE="train.json"
VALIDATION_FILE="validation.json"
TEST_FILE="test.json"
# selecting cross-encoder
model_name = "BAAI/bge-reranker-base"
# selectinga bi-encoder
bi_encoder_model_name="all-MiniLM-L6-v2"


from sentence_transformers import SentenceTransformer, util
model = SentenceTransformer('all-MiniLM-L6-v2')

#Sentences are encoded by calling model.encode()
emb1 = model.encode("Information Retrieval course at the University of Southern Maine for computer scientist.")
emb2 = model.encode("Best computer science course.")

cos_sim = util.cos_sim(emb1, emb2)
print("Cosine-Similarity:", cos_sim)

# Fine-tuning Cross-encoder
import csv
import datetime
import json
import string
from sentence_transformers import InputExample
from sentence_transformers import SentenceTransformer, util, CrossEncoder, losses
import torch
from sentence_transformers.cross_encoder.evaluation import CESoftmaxAccuracyEvaluator, CEBinaryClassificationEvaluator, \
    CERerankingEvaluator
from torch.utils.data import DataLoader
import math


def read_qrel_file(qrel_filepath):
    # a method used to read the topic file
    result = {}
    with open(qrel_filepath, "r") as f:
        reader = csv.reader(f, delimiter='\t', lineterminator='\n')
        for line in reader:
            query_id = line[0]
            doc_id = line[2]
            score = int(line[3])
            if query_id in result:
                result[query_id][doc_id] = score
            else:
                result[query_id] = {doc_id: score}
    # dictionary of key:query_id value: dictionary of key:doc id value: score
    return result


def load_topic_file(topic_filepath):
    # a method used to read the topic file for this year of the lab; to be passed to BERT/PyTerrier methods
    queries = json.load(open(topic_filepath,encoding='utf-8'))
    result = {}
    for item in queries:
      # You may do additional preprocessing here
      # returing results as dictionary of topic id: [title, body, tag]
      title = remove_html_tags(item['Title'].translate(str.maketrans('', '', string.punctuation)))
      body = remove_html_tags(item['Body'].translate(str.maketrans('', '', string.punctuation)))
      tags = item['Tags']
      result[item['Id']] = [title, body, tags]
    return result


def read_collection(answer_filepath):
  # Reading collection to a dictionary
  lst = json.load(open(answer_filepath,encoding='utf-8'))
  result = {}
  for doc in lst:
    result[doc['Id']] = remove_html_tags(doc['Text'])
  return result


## reading queries and collection
dic_topics = load_topic_file("topics_1.json")
dic_train=load_topic_file("./train.json")

queries = {}
train_queries={}

for query_id in dic_topics:
    queries[query_id] = "[TITLE]" + dic_topics[query_id][0] + "[BODY]" + dic_topics[query_id][1]
    
for query_id in dic_train:
    train_queries[query_id] = "[TITLE]" + dic_train[query_id][0] + "[BODY]" + dic_train[query_id][1]

    
qrel = read_qrel_file("qrel_1.tsv")
collection_dic = read_collection('Answers.json')

## Preparing pairs of training instances
num_topics = len(queries.keys())
number_training_samples = int(num_topics*0.9)


## Preparing the content
train_samples = []
valid_samples = {}
for qid in qrel:
    # key: doc id, value: relevance score
    dic_doc_id_relevance = qrel[qid]
    # query text
    topic_text=None
    train_text=None
    try:
        train_text=train_queries[qid]
    except:
        topic_text = queries[qid]
    

    if train_text:
        for doc_id in dic_doc_id_relevance:
            label = dic_doc_id_relevance[doc_id]
            content = collection_dic[doc_id]
            if label >= 1:
                label = 1
            train_samples.append(InputExample(texts=[train_text, content], label=label))
    else:
        for doc_id in dic_doc_id_relevance:
            label = dic_doc_id_relevance[doc_id]
            if qid not in valid_samples:
                valid_samples[qid] = {'query': topic_text, 'positive': set(), 'negative': set()}
            if label == 0:
                label = 'negative'
            else:
                label = 'positive'
            content = collection_dic[doc_id]
            valid_samples[qid][label].add(content)

print("Training and validation set prepared")


# Learn how to use GPU with this!
model = CrossEncoder(model_name)

# Adding special tokens
tokens = ["[TITLE]", "[BODY]"]
model.tokenizer.add_tokens(tokens, special_tokens=True)
model.model.resize_token_embeddings(len(model.tokenizer))

num_epochs = 2
model_save_path = "fine-tuned-bge-reranker-base"
train_dataloader = DataLoader(train_samples, shuffle=True, batch_size=4)
# During training, we use CESoftmaxAccuracyEvaluator to measure the accuracy on the dev set.
evaluator = CERerankingEvaluator(valid_samples, name='train-eval')
warmup_steps = math.ceil(len(train_dataloader) * num_epochs * 0.1)  # 10% of train data for warm-up
train_loss = losses.MultipleNegativesRankingLoss(model=model)
model.fit(train_dataloader=train_dataloader,
          evaluator=evaluator,
          epochs=num_epochs,
          warmup_steps=warmup_steps,
          output_path=model_save_path,
          save_best_model=True)

model.save(model_save_path)

# Fine-tuning Bi-encoder
# Models: https://sbert.net/docs/sentence_transformer/pretrained_models.html
from sentence_transformers import SentenceTransformer, SentencesDataset, InputExample, losses, evaluation
from torch.utils.data import DataLoader
from itertools import islice
import json
import torch
import math
import string
import csv
import random
import os
os.environ["WANDB_DISABLED"] = "true"

def read_qrel_file(file_path):
    # Reading the qrel file
    dic_topic_id_answer_id_relevance = {}
    with open(file_path) as fd:
        rd = csv.reader(fd, delimiter="\t", quotechar='"')
        for row in rd:
            topic_id = row[0]
            answer_id = int(row[2])
            relevance_score = int(row[3])
            if topic_id in dic_topic_id_answer_id_relevance:
                dic_topic_id_answer_id_relevance[topic_id][answer_id] = relevance_score
            else:
                dic_topic_id_answer_id_relevance[topic_id] = {answer_id: relevance_score}
    return dic_topic_id_answer_id_relevance


def load_topic_file(topic_filepath):
    # a method used to read the topic file for this year of the lab; to be passed to BERT/PyTerrier methods
    queries = json.load(open(topic_filepath,encoding='utf-8'))
    result = {}
    for item in queries:
      # You may do additional preprocessing here
      # returing results as dictionary of topic id: [title, body, tag]
      title = item['Title'].translate(str.maketrans('', '', string.punctuation))
      body = item['Body'].translate(str.maketrans('', '', string.punctuation))
      tags = item['Tags']
      result[item['Id']] = [title, body, tags]
    return result


def read_collection(answer_filepath):
  # Reading collection to a dictionary
  lst = json.load(open(answer_filepath,encoding='utf-8'))
  result = {}
  for doc in lst:
    result[int(doc['Id'])] = doc['Text']
  return result


# Uses the posts file, topic file(s) and qrel file(s) to build our training and evaluation sets.
def process_data(queries, train_dic_qrel, val_dic_qrel, collection_dic):
    train_samples = []
    evaluator_samples_1 = []
    evaluator_samples_2 = []
    evaluator_samples_score = []

    # Build Training set
    for topic_id in train_dic_qrel:
        question = queries[topic_id]
        dic_answer_id = train_dic_qrel.get(topic_id, {})

        for answer_id in dic_answer_id:
            score = dic_answer_id[answer_id]
            answer = collection_dic[answer_id]
            if score > 1:
                train_samples.append(InputExample(texts=[question, answer], label=1.0))
            else:
                train_samples.append(InputExample(texts=[question, answer], label=0.0))
    for topic_id in val_dic_qrel:
        question = queries[topic_id]
        dic_answer_id = val_dic_qrel.get(topic_id, {})

        for answer_id in dic_answer_id:
            score = dic_answer_id[answer_id]
            answer = collection_dic[answer_id]
            if score > 1:
                label = 1.0
            elif score == 1:
                label = 0.5
            else:
                label = 0.0
            evaluator_samples_1.append(question)
            evaluator_samples_2.append(answer)
            evaluator_samples_score.append(label)

    return train_samples, evaluator_samples_1, evaluator_samples_2, evaluator_samples_score



def shuffle_dict(d):
    keys = list(d.keys())
    random.shuffle(keys)
    return {key: d[key] for key in keys}


def split_train_validation(qrels, ratio=0.9):
    # Using items() + len() + list slicing
    # Split dictionary by half
    n = len(qrels)
    n_split = int(n * ratio)
    qrels = shuffle_dict(qrels)
    train = dict(islice(qrels.items(), n_split))
    validation = dict(islice(qrels.items(), n_split, None))

    return train, validation

def split_train_validation_with_defined_splits(qrels,train_topics,val_topics):
    # Using items() + len() + list slicing
    # Split dictionary by half
    train_qrels={}
    validation_qrels={}
    for train_topic in train_topics:
        if train_topic in qrels:
            train_qrels[train_topic]=qrels[train_topic]
    
    for val_topic in val_topics:
        if val_topic in qrels:
            validation_qrels[val_topic]=qrels[val_topic]
        
    return train_qrels, validation_qrels


def train(model):

    ## reading queries and collection
    dic_topics = load_topic_file("topics_1.json")
    train_topics=load_topic_file(TRAIN_FILE)
    val_topics=load_topic_file(VALIDATION_FILE)
    queries = {}
    for query_id in dic_topics:
        queries[query_id] = "[TITLE]" + dic_topics[query_id][0] + "[BODY]" + dic_topics[query_id][1]
    qrel = read_qrel_file("qrel_1.tsv")
    collection_dic = read_collection('Answers.json')
    train_dic_qrel, val_dic_qrel = split_train_validation_with_defined_splits(qrel,train_topics,val_topics)
    # print(train_dic_qrel)
    # print(val_dic_qrel)

    num_epochs = 100
    batch_size = 16

    # Rename this when training the model and keep track of results
    MODEL = "fine-tuned-all-MiniLM-L6-v2"

    # Creating train and val dataset
    train_samples, evaluator_samples_1, evaluator_samples_2, evaluator_samples_score = process_data(queries, train_dic_qrel, val_dic_qrel, collection_dic)

    train_dataset = SentencesDataset(train_samples, model=model)
    train_dataloader = DataLoader(train_dataset, shuffle = True, batch_size=batch_size)
    train_loss = losses.CosineSimilarityLoss(model=model)

    evaluator = evaluation.EmbeddingSimilarityEvaluator(evaluator_samples_1, evaluator_samples_2, evaluator_samples_score, write_csv="evaluation-epoch.csv")
    warmup_steps = math.ceil(len(train_dataloader) * num_epochs * 0.1) #10% of train data for warm-up

    # add evaluator to the model fit function
    model.fit(
        train_objectives =[(train_dataloader, train_loss)],
        evaluator=evaluator,
        epochs=num_epochs,
        warmup_steps=warmup_steps,
        use_amp=True,
        save_best_model=True,
        show_progress_bar=True,
        output_path=MODEL
    )



model = SentenceTransformer(bi_encoder_model_name)
device = torch.device("cuda:0" if torch.cuda.is_available() else "cpu")
print(device)
model.to(device)
train(model)