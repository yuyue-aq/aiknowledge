from app.services.section_context import page_heading


def test_only_explicit_page_headings_are_recovered():
    assert page_heading('02 项目经历：项目甲\n指标') == ('02 项目经历：项目甲',)
    assert page_heading('第三章 项目乙\n指标') == ('第三章 项目乙',)
    assert page_heading('指标为0.86。\n02 项目经历：其他项目') == ()
    assert page_heading(None) == ()
