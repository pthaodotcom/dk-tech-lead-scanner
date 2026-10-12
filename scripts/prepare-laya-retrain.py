"""Build a locally reviewed dataset without treating old model predictions as labels."""
from __future__ import annotations
import collections
import difflib
import hashlib
import json
import re
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / '.local/laya-training/retrain-2026-10-12'

# Labels assigned by reading the post text. T=train, V=validation, E=fresh evaluation.
# The three user-reported examples are corrections, never independent evaluation.
REVIEW = {
    '2227569228183167': ('service_request','automation','A','T'),
    '1616674009938577': ('service_request','website','A','T'),
    '1810012270111779': ('service_request','automation','review','T'),
    '1810022200110786': ('other','automation','A','T'),
    '1559589362518315': ('service_request','website','A','T'),
    '1613007637274452': ('service_request','software','review','T'),
    '1613619600546589': ('service_request','automation','review','V'),
    '1614322813809601': ('service_request','software','review','T'),
    '1615256893413622': ('service_request','website','A','V'),
    '1809789683467371': ('self_promotion','automation','review','T'),
    '1810026240110382': ('self_promotion','automation','review','T'),
    '1810689427018373': ('recruitment','software','A','T'),
    '1810730207014295': ('other','other','A','V'),
    '1811572636930052': ('other','software','A','T'),
    '1811614893592493': ('recruitment','other','A','E'),
    '1817160086150816': ('service_request','website','review','T'),
    '1817277812805710': ('service_request','automation','review','E'),
    '1820869788949698': ('self_promotion','website','A','T'),
    '1851772006068751': ('service_request','other','A','T'),
    '1852453279333957': ('service_request','other','A','V'),
    '1853109845934967': ('service_request','other','A','T'),
    '1853132322599386': ('service_request','other','A','T'),
    '1853150079264277': ('service_request','other','A','E'),
    '2085472395508819': ('self_promotion','website','A','T'),
    '2160322854693179': ('service_request','website','review','T'),
    '2160466584678806': ('service_request','website','review','T'),
    '2161354221256709': ('service_request','website','review','V'),
    '2219765348960585': ('other','software','A','T'),
    '2227053858234704': ('other','automation','A','T'),
    '2227449918195098': ('service_request','website','A','T'),
    '2227516991521724': ('service_request','automation','review','T'),
    '2227525878187502': ('other','other','A','E'),
    '2227544868185603': ('other','automation','review','T'),
    '2292410301520311': ('self_promotion','website','A','V'),
    '2292427331518608': ('self_promotion','website','A','T'),
    '2304851330353502': ('self_promotion','other','A','T'),
    '2304917777013524': ('self_promotion','website','A','T'),
    '2304932927012009': ('self_promotion','other','A','V'),
    '2304950750343560': ('self_promotion','website','A','E'),
    '2337395803779627': ('service_request','automation','review','T'),
    '2338006387051902': ('service_request','automation','A','E'),
    '2338146800371194': ('service_request','automation','review','E'),
    '2338216430364231': ('self_promotion','other','review','V'),
    '2338230353696172': ('self_promotion','automation','review','E'),
    '2338233640362510': ('self_promotion','automation','review','T'),
    '2362761344465931': ('service_request','website','A','E'),
    '2363018534440212': ('service_request','website','review','T'),
    '2576202706198456': ('self_promotion','other','A','T'),
    '2576207899531270': ('self_promotion','other','A','V'),
    '2576213179530742': ('self_promotion','other','review','T'),
    '2576219592863434': ('self_promotion','other','A','E'),
    '2576228032862590': ('self_promotion','other','A','T'),
    '2600864753760027': ('self_promotion','website','A','T'),
    '2600870837092752': ('self_promotion','website','A','T'),
    '2616418768793409': ('recruitment','other','A','T'),
    '2617379442030675': ('self_promotion','other','A','E'),
    '2726603677754077': ('other','other','A','T'),
    '28326189087059760': ('service_request','website','review','T'),
    '28335074629504539': ('self_promotion','software','A','T'),
    '28335311879480814': ('service_request','website','A','E'),
    '28335445666134102': ('self_promotion','software','A','E'),
    '28867387706235455': ('self_promotion','website','A','T'),
    '28876490768658482': ('self_promotion','website','A','V'),
    '28876948025279423': ('self_promotion','website','A','T'),
    '28877080298599529': ('self_promotion','website','A','T'),
    '28924312783926626': ('service_request','other','review','T'),
    '29331646253108898': ('service_request','software','A','E'),
    '29331872416419615': ('service_request','other','review','V'),
    '29336130802660443': ('other','other','A','E'),
    '29858490240406107': ('service_request','website','A','T'),
}

# Deliberately varied authored examples; families never cross dataset partitions.
SYNTHETIC = [
 ('T','service_request','website','A','Công ty tôi cần website giới thiệu dự án bất động sản, ai nhận làm xin báo giá.'),
 ('T','service_request','website','A','Mình cần thiết kế web cho doanh nghiệp kinh doanh nhà đất. Tìm đơn vị triển khai trọn gói.'),
 ('T','service_request','website','A','Cửa hàng muốn thuê làm trang web bán mỹ phẩm, có giỏ hàng và quản lý đơn.'),
 ('T','service_request','website','A','Tìm freelancer sửa giao diện Shopify và đưa sản phẩm của shop lên web.'),
 ('T','service_request','website','A','Cần làm landing page đăng ký tư vấn cho trung tâm đào tạo, bên nào nhận?'),
 ('T','service_request','website','A','Cần tích hợp đăng nhập OTP cho website của công ty, dùng SMS chính thức cho khách tự xác thực.'),
 ('T','service_request','software','A','Công ty cần thuê viết phần mềm quản lý kho và nhập xuất hàng, xin báo giá.'),
 ('T','service_request','software','A','Tìm bên triển khai ERP cho nhà máy, quản lý đơn hàng và sản xuất.'),
 ('T','service_request','software','A','Cần lập trình app học trực tuyến cho trường, theo dõi môn học và điểm danh.'),
 ('T','service_request','software','A','Muốn xây CRM quản lý khách hàng và lịch chăm sóc, ai nhận dự án này?'),
 ('T','service_request','software','A','Tìm dev làm ứng dụng đặt lịch khám cho phòng khám tư nhân, báo giá giúp.'),
 ('T','service_request','software','A','App quản lý nhân viên cần bổ sung xác thực hai bước cho tài khoản do nhân viên tự đăng ký.'),
 ('T','service_request','automation','A','Cần bot Telegram nhắc lịch trực cho đội của công ty, dùng bot API chính thức.'),
 ('T','service_request','automation','A','Tìm người làm tool tự động xuất báo cáo Excel từ dữ liệu nội bộ được cấp quyền.'),
 ('T','service_request','automation','A','Ai nhận viết API đồng bộ đơn hàng giữa hệ thống bán hàng và kế toán?'),
 ('T','service_request','automation','A','Cần tool CapCut tự ghép video sản phẩm do shop tự quay, thêm phụ đề hàng loạt.'),
 ('T','service_request','automation','A','Tìm người tự động sao lưu tài liệu nội bộ mỗi tối, có ghi log để kiểm tra.'),
 ('T','service_request','automation','review','Cần tool reg acc Telegram tự động với OTP thuê ngoài, ai code được?'),
 ('T','service_request','automation','review','Tìm bot tạo tài khoản tiktok us và đăng nhập hàng loạt, chưa nêu mục đích sử dụng.'),
 ('T','service_request','automation','review','Cần code tool nuôi acc và bơm tương tác, vượt xác minh bằng số thuê.'),
 ('T','service_request','automation','review','Ai cho thuê otp tele để tự đăng ký nhiều acc, cần người làm tool đăng nhập.'),
 ('T','service_request','software','review','Tìm người bypass khóa license file APK của bên khác, chưa có thông tin quyền sử dụng.'),
 ('T','service_request','website','review','Cần clone web y hệt video nhưng không có mô tả về ngành hay mục đích của website.'),
 ('T','service_request','other','A','Tìm designer làm logo và thiệp mời cho sự kiện của cửa hàng.'),
 ('T','service_request','other','A','Mình cần người dựng phối cảnh 3D cho quán cà phê, không yêu cầu phần mềm.'),
 ('T','service_request','website','B','Cần làm website casino nhận nạp tiền và đặt cược, tìm bên triển khai.'),
 ('T','service_request','software','B','Muốn thuê code app lừa người dùng nhập mã OTP ngân hàng để lấy tiền.'),
 ('T','service_request','automation','B','Tìm bot gửi link giả mạo ngân hàng để lấy mật khẩu và mã xác nhận.'),
 ('T','service_request','website','B','Cần trang tài xỉu và game bài ăn tiền, ai nhận làm?'),
 ('T','self_promotion','website','A','Bên mình nhận thiết kế website doanh nghiệp, khách có nhu cầu inbox để xem mẫu.'),
 ('T','self_promotion','software','A','Đội mình cung cấp phần mềm CRM và ERP, dùng thử miễn phí rồi liên hệ đặt mua.'),
 ('T','self_promotion','automation','A','Em bán tool tự tạo phụ đề video và xuất báo cáo, ai cần ib để mua.'),
 ('T','self_promotion','automation','review','Kho tool auto reg acc, OTP thuê, spam tin nhắn và bypass license. Inbox đặt mua.'),
 ('T','other','automation','A','Hướng dẫn tạo bot trợ lý AI trên điện thoại để edit video và đăng bài. Đây là bài chia sẻ cách làm.'),
 ('T','other','automation','A','Cách tạo bot Telegram nhắc lịch: bài hướng dẫn chi tiết cho người mới, không thuê người code.'),
 ('T','other','website','A','Chia sẻ cách tự dựng trang web nội thất bằng Wix, mọi người tham khảo bài hướng dẫn.'),
 ('T','other','software','A','Giải thích JDK là gì và cách cài để học lập trình Java. Không có nhu cầu thuê dịch vụ.'),
 ('T','other','automation','review','Chia sẻ mẹo lách waitlist bằng VPN và tạo nhiều acc để nhận credit miễn phí.'),
 ('T','recruitment','software','A','Công ty tuyển lập trình viên ERP full time, lương 20 triệu, gửi CV để ứng tuyển.'),
 ('T','recruitment','website','A','Tuyển nhân viên frontend vào team nội bộ, làm tại văn phòng và có bảo hiểm.'),
 ('V','service_request','website','A','Doanh nghiệp du lịch đang tìm nhà cung cấp làm website đặt tour, cần báo giá trọn gói.'),
 ('V','service_request','software','A','Bên tôi thuê phát triển hệ thống quản lý lịch bảo trì máy móc cho xưởng.'),
 ('V','service_request','automation','A','Cần API nối phần mềm vận chuyển và kho để đồng bộ trạng thái đơn.'),
 ('V','service_request','other','A','Thuê người vẽ minh họa sách thiếu nhi theo brief của nhà xuất bản.'),
 ('V','service_request','automation','review','Tìm tool đăng ký nick Zalo số lượng lớn qua dịch vụ nhận mã xác thực thuê.'),
 ('V','service_request','website','B','Ai làm trang cá cược bóng đá nạp rút tiền cho khách, xin báo giá.'),
 ('V','self_promotion','software','A','Chúng tôi bán phần mềm chấm công, xin mời doanh nghiệp liên hệ để mua.'),
 ('V','other','automation','A','Video hướng dẫn tự làm workflow tổng hợp nội dung bằng AI, không tuyển dev hay đặt hàng.'),
 ('V','recruitment','other','A','Tuyển chuyên viên thiết kế đồ họa vào công ty, hưởng lương tháng, cần nộp CV.'),
 ('E','service_request','website','A','Nhờ bên có kinh nghiệm triển khai website cho hãng vận tải, có mục nhận yêu cầu chở hàng.'),
 ('E','service_request','software','A','Phòng khám muốn đặt làm ứng dụng lưu hồ sơ khám và đặt lịch, tìm đối tác thực hiện.'),
 ('E','service_request','automation','A','Đơn vị tôi tìm nhà thầu tự động đối chiếu hóa đơn từ file kế toán nội bộ.'),
 ('E','service_request','other','A','Đặt thuê chụp ảnh sản phẩm bộ sưu tập quần áo, ai nhận báo giúp mình.'),
 ('E','service_request','automation','review','Muốn đặt viết chương trình mở nhiều tài khoản trên mạng xã hội bằng mã xác minh mua từ người khác.'),
 ('E','service_request','software','B','Thuê phát triển ứng dụng đánh bạc trực tuyến với ví đặt cược đổi thưởng.'),
 ('E','self_promotion','website','A','Agency vừa ra mắt gói web cho khách sạn, chúng tôi mời khách liên hệ để đăng ký dịch vụ.'),
 ('E','other','software','A','Tổng hợp kiến thức SQL cho người bắt đầu học, đây là tài liệu tham khảo không cần ai làm hộ.'),
 ('E','recruitment','automation','A','Đội nhân sự tuyển kỹ sư tự động hóa làm nhân viên chính thức, gửi hồ sơ xin việc.'),
]

# Additional annotations of the original training posts, read directly from their
# text. Held-out legacy labels and partition assignments stay unchanged.
LEGACY_AUX = {
    'other': ['1564886382320679','1809634206816252','1403369834795363','4677223965931122',
        '4677222475931271','1564854522323865','1783146422936603','1841938536839391',
        '1639196761048178','2085074735548585','1783119232939322','4677153689271483',
        '1841914383508473','4677135789273273','1592840825953334','2291953238232684',
        '2219713798965740','3522940384547214','4893674584193194','1592619649308785',
        '938154082366543','2291699538258054','2291699218258086','1850955746150377',
        '937976445717640','1850552279524057','1849100383002580','29319463417660515','1808732263573113'],
    'website': ['1564885348987449','1128887156363378','2219763535627433','1639140524387135',
        '2155259988687436','2160414358017362','29867919369463194','29842668315321633',
        '29856837557238042','3522930037881582','3522929847881601','2226911071582316',
        '1592656962638387','2084868048902587','1403127064819640','2084850508904341',
        '2226639758276114','2726697651078013','4892030614357591','4892018744358778',
        '4891931827700803','2154697842076984','1878480993525466'],
    'automation': ['2337645877087953','2337623893756818','2226869801586443',
        '1612289387346277','1612633887311827','2226605468279543','28829613503389938',
        '2226383121635111','2337047077147833'],
    'software': ['2219189559018164'],
}
LEGACY_REVIEW = {'2337645877087953','2160414358017362','2337623893756818','2226869801586443',
    '1612289387346277','1612633887311827','2226605468279543','2219189559018164',
    '2226383121635111','2337047077147833','1808732263573113'}
SYNTHETIC.extend([
 ('T','service_request','automation','A','Tìm dev code tool tìm ảnh và video theo keywords, báo giá giúp mình.'),
 ('T','service_request','automation','A','Cần người viết crawler lấy nguồn hình ảnh và clip theo từ khóa, liên hệ Telegram.'),
 ('T','service_request','automation','A','Ai nhận làm công cụ quét ảnh sản phẩm theo danh sách từ khóa để tổng hợp kết quả?'),
 ('T','service_request','automation','A','Muốn thuê code bot tìm nguồn video theo keyword và lưu đường dẫn, ai làm được inbox.'),
 ('T','service_request','automation','A','Cần tool tìm kiếm hình ảnh và video theo chủ đề, liên hệ tg để trao đổi yêu cầu.'),
 ('T','service_request','automation','A','Tìm người làm tool thu thập dữ liệu ảnh công khai theo keywords. Xin báo giá.'),
 ('T','other','automation','A','Chia sẻ hướng dẫn tự viết crawler ảnh theo từ khóa, mọi người tham khảo.'),
 ('T','self_promotion','automation','A','Bên mình nhận code tool tìm kiếm video và hình ảnh theo keyword. Khách cần inbox đặt làm.'),
 ('V','service_request','automation','A','Shop cần thuê xây công cụ tìm ảnh tham khảo theo danh sách chủ đề, xin giá triển khai.'),
 ('E','service_request','automation','A','Đặt làm chương trình tổng hợp link hình và clip từ kết quả tìm kiếm theo chủ đề, bên nào nhận?'),
 ('T','self_promotion','software','A','Đội chúng tôi nhận triển khai phần mềm kế toán theo yêu cầu, khách cần dịch vụ xin liên hệ để lấy báo giá.'),
 ('T','self_promotion','software','A','Bạn đang cần hệ thống quản lý kho? Chúng tôi cung cấp giải pháp sẵn và nhận tùy chỉnh theo nhu cầu khách.'),
 ('T','self_promotion','software','A','Công ty em phát triển ứng dụng cho doanh nghiệp. Khách muốn đặt làm app vui lòng inbox bên em.'),
 ('T','self_promotion','automation','A','Dịch vụ bên mình: đồng bộ dữ liệu API và xây workflow nội bộ cho doanh nghiệp. Liên hệ để thuê bên mình.'),
 ('T','self_promotion','website','A','Khách cần sửa website hãy nhắn cho đội em. Bên em nhận trực tiếp fix web theo yêu cầu.'),
 ('T','self_promotion','other','A','Mình nhận thiết kế bao bì và key visual sự kiện. Nếu các bạn đang cần designer hãy đặt dịch vụ bên mình.'),
 ('T','other','other','A','Tôi đang tìm việc quản lý dự án, xin gửi CV và kết nối với nhà tuyển dụng. Tôi không thuê bên ngoài làm dự án.'),
 ('T','service_request','software','A','Tìm đội nhận phát triển ERP quản lý quy trình nhân sự, có hợp đồng triển khai.'),
 ('T','service_request','software','A','Bên mình thuê làm hệ thống kế toán và tính lương, cần người báo giá phần mềm.'),
 ('T','service_request','software','A','Cần xây ứng dụng điện thoại quản lý lịch học, tìm nhà thầu lập trình.'),
 ('T','service_request','software','A','Tìm đơn vị nhận làm phần mềm quản lý hồ sơ và tài sản của văn phòng.'),
 ('T','other','software','A','Chia sẻ kiến thức dùng cơ sở dữ liệu trong phần mềm ERP, ai học thì xem tài liệu này.'),
 ('T','service_request','automation','A','Muốn tự động xuất hóa đơn từ file Excel được doanh nghiệp cấp quyền, cần người viết tool.'),
 ('T','service_request','automation','A','Bên mình thuê lập trình API để kết nối máy bán hàng với phần mềm kế toán.'),
 ('T','service_request','automation','A','Ai nhận tích hợp webhook của kho hàng để tự cập nhật dữ liệu vào CRM nội bộ?'),
 ('T','service_request','automation','review','Tìm bên bán tài khoản mạng xã hội và tool tự tăng follow, chưa có thông tin về quyền vận hành.'),
 ('T','self_promotion','other','review','Bán nick quảng cáo, shop cũ và kênh mạng xã hội đã nuôi sẵn, inbox để giao dịch.'),
 ('T','service_request','other','A','Cần thuê người làm ảnh quảng cáo cho sản phẩm của cửa hàng, có brief và ngân sách rõ.'),
 ('T','self_promotion','other','A','Nhà mình bán bún và bánh cuốn, nhận giao đồ ăn trong khu vực, ai mua thì nhắn.'),
 ('T','self_promotion','other','A','Tôi cung cấp thiết bị điện gia dụng, có giá bán và bảo hành, mời khách mua hàng.'),
 ('T','service_request','website','A','Xin báo giá trang web cho đơn vị tổ chức hội nghị, cần danh mục sự kiện và form đăng ký.'),
 ('T','service_request','website','A','Công ty muốn có website giới thiệu thương hiệu và sản phẩm, đặt thuê bên nhận thực hiện.'),
])

def norm(text):
    return re.sub(r'\s+', ' ', text.lower()).strip()

def main():
    OUT.mkdir(parents=True, exist_ok=True)
    rows = [json.loads(line) for line in (ROOT/'data/laya/post_type_dataset.jsonl').read_text(encoding='utf-8').splitlines() if line.strip()]
    for service,identifiers in LEGACY_AUX.items():
        for row in rows:
            if row['id'] in identifiers:
                row.update(service_label=service,safety_label='review' if row['id'] in LEGACY_REVIEW else 'A')
    split_names = {'T':'train','V':'validation','E':'test'}
    reviewed=[]
    with sqlite3.connect(ROOT/'.local/dk-tech-lead-scanner/scanner.sqlite3') as db:
        db.row_factory=sqlite3.Row
        for identifier, (label,service,safety,split) in REVIEW.items():
            record=db.execute('SELECT id,text,group_name FROM posts WHERE id=?',(identifier,)).fetchone()
            if record is None:
                raise ValueError(f'Missing reviewed source post {identifier}')
            row=dict(record)
            matching=next((old for old in rows if norm(old['text'])==norm(row['text']) or
                difflib.SequenceMatcher(None,norm(old['text']),norm(row['text']),autojunk=False).ratio()>.91),None)
            if matching:
                if matching['label'] != label:
                    # A corrected family remains in its prior split; never move test text into train.
                    matching['label']=label
                matching.update(service_label=service,safety_label=safety)
                row['split']=matching['split'];row['duplicate_of']=matching['id']
            else:
                row.update(label=label,service_label=service,safety_label=safety,split=split_names[split],
                           origin='local_review',label_source='assistant_text_review',source_ids=[identifier],
                           content_group=hashlib.sha256(norm(row['text']).encode()).hexdigest())
                rows.append(row)
            reviewed.append({**row,'reviewed_labels':{'post_type':label,'service':service,'safety':safety}})
    for index,(split,label,service,safety,text) in enumerate(SYNTHETIC):
        rows.append({'id':f'2026-10-12-synthetic-{index:03d}','text':text,'label':label,
                     'service_label':service,'safety_label':safety,'split':split_names[split],
                     'origin':'synthetic_assistant','content_group':hashlib.sha256(norm(text).encode()).hexdigest(),
                     'label_source':'explicitly_authored_example'})
    (OUT/'dataset.jsonl').write_text(''.join(json.dumps(row,ensure_ascii=False)+'\n' for row in rows),encoding='utf-8')
    (OUT/'reviewed-real-posts.json').write_text(json.dumps(reviewed,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'rows':len(rows),'realPostsReviewed':len(reviewed),'syntheticAdded':len(SYNTHETIC),
        'splits':dict(collections.Counter(row['split'] for row in rows)),
        'newRealEvaluation':sum(row['split']=='test' and row['origin']=='local_review' for row in rows)},ensure_ascii=True),flush=True)

if __name__=='__main__': main()
