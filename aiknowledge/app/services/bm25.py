"""Scope-local Okapi BM25, positive IDF, Chinese bigrams and intact identifiers.

Unlike candidate reranking, callers pass the complete authorized live corpus.
Scores use the classic (k1+1) TF factor; they are not cosine probabilities.
"""
from collections import Counter
from dataclasses import replace
from math import log1p
import re
import unicodedata

from app.domain.retrieval import RetrievalError

ANALYZER = 'zh-bigram-identifiers-v1'


def analyze(text: str) -> list[str]:
    normalized=unicodedata.normalize('NFKC',text).casefold()
    terms=[]
    for word in re.findall(r'[a-z0-9_]+(?:[.:/-][a-z0-9_]+)*(?:\+{1,2}|#)?|[\u3400-\u9fff]+',normalized):
        if re.fullmatch(r'[\u3400-\u9fff]+',word) and len(word)>1:
            terms.extend(word[i:i+2] for i in range(len(word)-1))
        else:terms.append(word)
    return terms


class Bm25Retriever:
    def __init__(self, *, max_corpus_chunks=5000, max_corpus_characters=2_000_000):
        if max_corpus_chunks<1 or max_corpus_characters<1:raise ValueError('Invalid corpus budget')
        self.max_corpus_chunks=max_corpus_chunks
        self.max_corpus_characters=max_corpus_characters
        self.k1,self.b=1.2,.75

    @property
    def config(self):
        return {'score_kind':'bm25','analyzer':ANALYZER,'k1':self.k1,'b':self.b,'idf':'positive-log1p',
                'tf_scaling':'classic-k1-plus-one','max_corpus_chunks':self.max_corpus_chunks,
                'max_corpus_characters':self.max_corpus_characters,'statistics_scope':'authorized-live-chunks'}

    def rank(self, question, corpus, top_k):
        if not isinstance(question,str) or not question.strip() or len(question.strip())>2000:
            raise RetrievalError('RETRIEVAL_INPUT_INVALID','请输入1—2000字的问题。',422)
        if isinstance(top_k,bool) or not isinstance(top_k,int) or not 1<=top_k<=20:
            raise RetrievalError('RETRIEVAL_INPUT_INVALID','Top K必须为1—20的整数。',422)
        if len(corpus)>self.max_corpus_chunks or sum(len(x.content) for x in corpus)>self.max_corpus_characters:
            raise RetrievalError('BM25_CORPUS_LIMIT','当前可用片段超过关键词检索上限，请缩小测试空间后重试。',422)
        unique={x.id:x for x in corpus}
        items=list(unique.values())
        terms=set(analyze(question))
        if not items or not terms:return ()
        docs=[Counter(analyze(x.content)) for x in items]
        lengths=[sum(d.values()) for d in docs]
        average=sum(lengths)/len(items) or 1.
        idfs={t:log1p((len(items)-sum(t in d for d in docs)+.5)/(sum(t in d for d in docs)+.5)) for t in terms}
        hits=[]
        for item,doc,length in zip(items,docs,lengths):
            score=sum(idfs[t]*doc[t]*(self.k1+1)/(doc[t]+self.k1*(1-self.b+self.b*length/average)) for t in terms if doc[t])
            if score>0:hits.append(replace(item,score=score))
        return tuple(sorted(hits,key=lambda x:(-x.score,str(x.id)))[:top_k])
