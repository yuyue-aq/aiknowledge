"""Freeze new synthetic paragraph evidence before live ranking or tuning."""
from pathlib import Path
import hashlib,json
from reportlab.pdfgen import canvas
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

ROOT=Path(__file__).resolve().parents[3];BASE=ROOT/'eval/p1/chunk';MAT=BASE/'materials'
MAT.mkdir(parents=True,exist_ok=True)
pdfmetrics.registerFont(TTFont('AcceptanceChinese','C:/Windows/Fonts/msyh.ttc',subfontIndex=0))
SERVICES=[('青桥',16,46,5,'DQ-101','资料管理员'),('星埠',22,62,7,'DQ-202','空间拥有者'),
          ('海栈',28,88,9,'DQ-303','技术维护员'),('云港',34,104,11,'DQ-404','知识管理员'),
          ('风禾',40,130,13,'DQ-505','高级协作者')]
cases=[];materials={}
HOLDOUT={2,8,13,19,21,27,34,40,45,50}
for index,(name,trial,retain,size,code,role) in enumerate(SERVICES,1):
    sections=[('资料说明','仅用于D阶段结构分块验收，全部为虚构服务，不代表实际产品运营规则。'),
        ('试用期限',f'{name}测试版试用期限为{trial}天。'),('保留周期',f'{name}停用后资料保留{retain}天。'),
        ('容量约束',f'{name}单份资料上限为{size}MB，超过上限必须明确拒绝。'),
        ('异常标识',f'{name}同步异常代码为{code}，先核对版本再同步。'),
        ('审批角色',f'{name}范围变更由{role}审批，访客不能审批。'),
        ('重复同步',f'{name}每次同步必须使用唯一请求标识，重复标识不重复导入。'),
        ('访问边界',f'{name}访客仅能使用公开分类归纳问答，没有原始文件下载入口。'),
        ('计算范围',f'{name}允许根据已提供的试用期限和保留周期计算差值，必须标注为推算。'),
        ('资料未记录',f'本资料没有记录{name}的订阅价格、真实公网地址或客户数量。')]
    plain=f'虚构验收服务：{name}\n'
    markdown=f'# 虚构验收服务：{name}\n\n'
    for number,(heading,text) in enumerate(sections,1):
        plain+=f'{number:02d} {heading}\n{text}\n\n'
        markdown+=f'## {number:02d} {heading}\n{text}\n\n'
    stem=f'{index:02d}-{name}'
    (MAT/(stem+'.txt')).write_text(plain,encoding='utf-8')
    (MAT/(stem+'.md')).write_text(markdown,encoding='utf-8')
    pdf=canvas.Canvas(str(MAT/(stem+'.pdf')),pagesize=(595,842));pdf.setTitle(stem+'虚构分块验收')
    pdf.setFont('AcceptanceChinese',18);pdf.drawString(46,798,f'虚构验收服务：{name}')
    y=756
    for number,(heading,text) in enumerate(sections,1):
        pdf.setFont('AcceptanceChinese',12);pdf.drawString(46,y,f'{number:02d} {heading}');y-=21
        pdf.setFont('AcceptanceChinese',10)
        for start in range(0,len(text),44):pdf.drawString(46,y,text[start:start+44]);y-=18
        y-=12
    pdf.setFont('AcceptanceChinese',9);pdf.drawString(46,28,'独立D阶段资料，不与原版14天/30天的500题档案混用。');pdf.save()
    questions=[(f'{name}能试用多少天？',str(trial)+'天',[str(trial)+'天']),
        (f'{name}停用之后，资料还保留多久？',str(retain)+'天',[str(retain)+'天']),
        (f'{name}一个文件的容量限制是多少？',str(size)+'MB',[str(size)+'MB']),
        (f'{name}同步异常的标识是什么？',code,[code]),
        (f'谁有权审批{name}的范围修改？',role,[role]),
        (f'{name}重复使用同步请求标识会重复导入吗？','不会重复导入',['重复标识不重复导入']),
        (f'{name}的访客能下载原始文件吗？','没有原始文件下载入口',['没有原始文件下载入口']),
        (f'{name}的保留周期比试用期限多多少天？',f'推算相差{retain-trial}天',[str(trial)+'天',str(retain)+'天']),
        (f'请分别列出{name}的试用期限和资料保留周期。',f'{trial}天；{retain}天',[str(trial)+'天',str(retain)+'天']),
        (f'{name}的订阅价格多少钱？','资料未记录，不应猜测',[])]
    for q,answer,literals in questions:
        n=len(cases)+1;fmt=['pdf','md','txt'][(n-1)%3]
        cases.append({'id':f'D{n:03d}','split':'holdout' if n in HOLDOUT else 'tune','format':fmt,
            'service':name,'document':stem+'.'+fmt,'question':q,'expected_answer':answer,
            'answerable':bool(literals),'evidence_literals':literals})
    for fmt in ['pdf','md','txt']:
        p=MAT/(stem+'.'+fmt);materials[p.name]=hashlib.sha256(p.read_bytes()).hexdigest()
(BASE/'cases.json').write_text(json.dumps(cases,ensure_ascii=False,indent=2),encoding='utf-8')
manifest={'date':'2026-10-09','cases':50,'split':{'tune':40,'holdout':10},
    'gold_sha256':hashlib.sha256((BASE/'cases.json').read_bytes()).hexdigest(),'material_sha256':materials,
    'frozen_before_live_ranking':True,'notes':'Five newly synthetic services, three formats, independent spaces per format. Literal evidence coverage is not semantic answer accuracy; numeric questions derive values; five missing-price questions must refuse.'}
(BASE/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
print('Frozen new D corpus: 15 files, 50 cases, 40 tune / 10 holdout')
