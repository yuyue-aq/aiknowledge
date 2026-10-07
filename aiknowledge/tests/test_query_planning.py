from app.services.query_planning import parse_queries,complex_question
import pytest


@pytest.mark.parametrize('question', [
    '请逐项回答：1）申请截止时间；2）审批负责人。',
    '请回答：1. 报销周期；2. 财务联系人。',
    '请回答：1、仓库开放时间；2、值班负责人。',
    '缓存负责什么且不负责什么？',
])
def test_independent_requirements_trigger_context_planning(question):
    assert complex_question(question)


def test_number_in_single_fact_is_not_a_task_list():
    assert not complex_question('版本1.0的试用期是多少？')


def test_subquery_limits_and_deduplication():
    assert parse_queries('{"queries":["甲职责","甲职责","原问题"]}','原问题') == ('甲职责',)
    assert parse_queries('{"queries":["a","b","c","d","e"]}','问题') == ()
    assert parse_queries('{"queries":[null]}','问题') == ()
    assert parse_queries('{"queries":["'+'x'*201+'"]}','问题') == ()
    assert complex_question('部署方式是什么？有公网地址吗？')
    assert not complex_question('谁负责后端？')
