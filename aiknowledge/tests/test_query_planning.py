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


def test_subqueries_preserve_identifiers_dates_and_negated_constraints():
    question = '项目 PRJ-A17 于 2026-09-30 尚未开放；请分别说明版本 1.2 和访客权限。'
    content = '{"queries":["PRJ-A17 2026-09-30 尚未开放的版本 1.2","PRJ-A17 2026-09-30 访客权限，版本 1.2 尚未开放"]}'

    assert parse_queries(content, question) == (
        'PRJ-A17 2026-09-30 尚未开放的版本 1.2',
        'PRJ-A17 2026-09-30 访客权限，版本 1.2 尚未开放',
    )


@pytest.mark.parametrize(
    'content',
    [
        '{"queries":["PRJ-A17 访客权限","PRJ-A17 版本 1.2"]}',
        '{"queries":["PRJ-A17 2026-09-30 已开放版本 1.2","PRJ-A17 2026-09-30 访客权限"]}',
        '{"queries":["PRJ-A17 2026-09-30 尚未开放的版本 1.2","PRJ-A17 2026-09-30 访客权限"]}',
    ],
)
def test_subqueries_fall_back_when_constraints_are_omitted(content):
    question = '项目 PRJ-A17 于 2026-09-30 尚未开放；请分别说明版本 1.2 和访客权限。'

    assert parse_queries(content, question) == ()
