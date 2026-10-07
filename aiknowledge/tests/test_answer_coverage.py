from app.services.answer_coverage import comparison_cells,render_coverage


def test_generic_named_comparison_and_three_object_fallback():
    assert comparison_cells('系统X与Y分别如何使用MySQL和Redis？') == (('系统X','MySQL'),('系统X','Redis'),('系统Y','MySQL'),('系统Y','Redis'))
    assert comparison_cells('项目A与B和C分别如何使用Redis和MySQL？') == ()
    assert comparison_cells('说明Redis用途') == ()


def test_missing_cell_or_unretrieved_citation_is_rejected():
    cells=(('系统X','Redis'),('系统Y','Redis'))
    row={'object':'系统X','aspect':'Redis','available':True,'answer':'缓存','citation_ids':['C99']}
    assert render_coverage([row],cells,{'C1'}) is None
    assert render_coverage([row],(cells[0],),{'C1'}) is None


def test_unavailable_cell_cannot_render_a_fabricated_value():
    row={'object':'系统X','aspect':'Redis','available':False,'answer':'编造的用途','citation_ids':['C99']}
    answer,aliases=render_coverage([row],(('系统X','Redis'),),{'C1'})
    assert '编造' not in answer
    assert aliases == []


def test_asymmetric_request_does_not_invent_extra_object_component_cell():
    cells=comparison_cells('比较项目A与B：A只解释PostgreSQL、pgvector、Redis三项；B只解释PostgreSQL、Redis两项。不要增加B的pgvector项。')
    assert len(cells)==5
    assert ('项目B','pgvector') not in cells
