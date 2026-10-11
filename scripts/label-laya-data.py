"""Reviewed labels for the 11 Oct dashboard paste; never use previous Laya predictions as targets."""
from __future__ import annotations

import collections
import difflib
import hashlib
import json
import random
from pathlib import Path

from importlib.machinery import SourceFileLoader

ROOT = Path(__file__).resolve().parents[1]
normalize_group = SourceFileLoader("prepare_laya_data", str(ROOT / "scripts/prepare-laya-data.py")).load_module().content_group
REQUESTS = {14,23,39,40,41,42,43,44,45,46,67,68,69,70,71,73,76,77,78,79,80,85,86,87,88,96,97}
OTHER = {17,22,24,28,47,50,66,72,94,95,98,100}
RECRUITMENT = {99}
NOTES = {
    14: "Tác giả cần xây lại website B2B và mời nhà cung cấp nhận brief.",
    36: "Người đăng tìm job để tự cung cấp dịch vụ thiết kế, không phải khách thuê.",
    49: "Nội dung dẫn tới lời chào thiết kế website taxi cho người đọc.",
    50: "Hướng dẫn nhúng Fanpage; không có lời tìm nhà cung cấp hay chào dịch vụ rõ.",
    53: "Mở đầu 'Cần API' nhưng đang chào bán API của mình, có bảng giá và link đăng ký.",
    72: "Hỏi người am hiểu công cụ; chưa nói rõ cần mua/thuê một dịch vụ.",
    76: "Thuê freelancer thiết kế ảnh sản phẩm cụ thể, không tuyển nhân viên vào đội ngũ.",
    79: "Thuê theo sản phẩm Key Visual, budget và mức phí dự án; không phải tuyển nhân sự.",
    87: "Thuê Dev/Team làm middleware có đầu ra và báo giá; hashtag tuyển dụng không đổi ý định.",
    94: "Khảo sát sản phẩm hiện có, không tìm nhà cung cấp.",
    95: "Hỏi tư vấn ý tưởng/chức năng bài học; chưa có yêu cầu thuê triển khai.",
    99: "Tuyển nhân viên Content SEO full-time, có lương, địa điểm làm việc và yêu cầu gửi CV.",
    100: "Mời dùng thử một app đang thử nghiệm; không yêu cầu nhà cung cấp triển khai.",
}
QUESTION = {
    "type": "choice",
    "instructions": "Phân loại mục đích chính của tác giả bài viết. Thuê bên ngoài làm một sản phẩm/dự án khác với tuyển nhân viên. Đọc cả bài; câu hỏi quảng cáo hướng tới người đọc không phải nhu cầu của người đăng.",
    "criteria": {
        "service_request": "Khách hàng cần thuê/mua dịch vụ hoặc sản phẩm, tìm người/đơn vị làm dự án cho mình, hỏi báo giá. Thuê freelancer theo sản phẩm cũng thuộc loại này.",
        "recruitment": "Tuyển nhân viên, intern, cộng tác viên vào đội ngũ. Có vị trí làm việc, lương, CV, ứng tuyển hoặc yêu cầu nhân sự.",
        "self_promotion": "Người đăng chào bán/nhận cung cấp dịch vụ, sản phẩm, tự giới thiệu năng lực; mời khách inbox, đặt mua hoặc nhận tư vấn của mình.",
        "other": "Chia sẻ kiến thức, thảo luận, chào thành viên, khảo sát, hỏi lời khuyên hoặc mời thử sản phẩm; không thuộc ba loại trên.",
    },
}
SYNTHETIC_RECRUITMENT = [
    "Công ty tuyển lập trình viên backend làm việc tại văn phòng. Lương thỏa thuận, gửi CV cho phòng nhân sự.",
    "Team đang tuyển frontend developer chính thức. Yêu cầu React, làm việc 5 ngày/tuần, có bảo hiểm và ngày phép.",
    "Tìm nhân viên IT support cho công ty, hỗ trợ máy tính nội bộ. Làm giờ hành chính và gửi hồ sơ ứng tuyển.",
    "TUYỂN THỰC TẬP SINH LẬP TRÌNH WEB. Được đào tạo, có trợ cấp hàng tháng và cơ hội lên nhân viên chính thức.",
    "Bên mình tuyển designer in-house làm lâu dài. Lương cố định, thưởng cuối năm; ứng viên gửi CV và portfolio.",
    "Tuyển chuyên viên triển khai ERP vào phòng dự án, có kinh nghiệm Odoo. Làm việc toàn thời gian tại công ty.",
    "Doanh nghiệp cần tuyển Business Analyst chính thức cho đội phần mềm. Quyền lợi bảo hiểm và lương tháng cạnh tranh.",
    "Tuyển nhân viên marketing online cho cửa hàng. Công việc chạy quảng cáo và quản lý fanpage, thời gian 8h đến 17h.",
    "Mở vị trí mobile developer. Hồ sơ gửi bộ phận HR, phỏng vấn kỹ thuật và ký hợp đồng lao động.",
    "Tuyển QA tester junior vào team sản phẩm. Chấp nhận sinh viên mới tốt nghiệp, hỗ trợ đào tạo trong thời gian thử việc.",
    "Mình đang tuyển một bạn vận hành hệ thống làm ca cố định. Có phụ cấp và chế độ nghỉ phép, inbox nhận JD.",
    "Cần nhân viên thiết kế đồ họa làm việc tại studio, lương tháng. Gửi hồ sơ và sản phẩm đã làm để phỏng vấn.",
    "Công ty bổ sung nhân sự Python developer làm việc remote dài hạn. Nhận lương hàng tháng, ứng tuyển qua email HR.",
    "Tuyển cộng tác viên viết nội dung vào đội marketing, làm theo lịch hàng tuần và hưởng phụ cấp tháng.",
    "TUYỂN DỤNG NHÂN VIÊN CHĂM SÓC KHÁCH HÀNG PHẦN MỀM. Yêu cầu giao tiếp tốt, lương cơ bản và hoa hồng.",
    "Tìm intern UX/UI tham gia đội thiết kế sản phẩm trong 3 tháng. Có mentor và trợ cấp, gửi CV cùng portfolio.",
    "Công ty đang tuyển trưởng nhóm kỹ thuật quản lý đội dev, cần kinh nghiệm dẫn dắt. Ứng tuyển bằng hồ sơ năng lực.",
    "Bên mình tuyển kỹ sư tích hợp hệ thống chính thức, onsite tại nhà máy. Lương theo năng lực và bảo hiểm đầy đủ.",
    "Cần tuyển nhân viên quản trị website của doanh nghiệp, cập nhật sản phẩm hàng ngày. Làm toàn thời gian tại văn phòng.",
    "Studio mở vị trí 3D artist trong team game, lương cố định và phỏng vấn portfolio. Không nhận dịch vụ ngoài.",
    "Team có headcount mới cho kỹ sư automation, làm chính thức và nhận chế độ nhân viên. Bạn quan tâm gửi resume.",
    "[Hiring] Backend engineer, full-time, office in HCMC. Please send your resume and expected monthly salary.",
    "Tuyển nhân viên kinh doanh phần mềm CRM cho chi nhánh. Chế độ thử việc, lương cơ bản, KPI và BHXH.",
    "Tìm một bạn coder vào đội nội bộ làm lâu dài, có hợp đồng lao động và lương tháng, gửi CV để hẹn phỏng vấn.",
]
SYNTHETIC_REQUESTS = [
    "Cần tìm freelancer thiết kế landing page cho dự án một lần. Gửi portfolio và báo giá theo sản phẩm nhé.",
    "Bên mình cần thuê đội dev viết hệ thống quản lý nhân sự, không tuyển nhân viên. Ai làm được gửi báo giá.",
    "Tuyển freelancer nhận làm website bán hàng theo hợp đồng dự án, nghiệm thu rồi thanh toán. Nhờ gửi mức phí.",
    "Có agency nào nhận thiết kế app đặt lịch cho spa không? Mình cần tư vấn giải pháp và dự toán.",
    "Mình cần bên viết bot tổng hợp báo cáo doanh thu mỗi ngày, ai nhận dự án liên hệ mình.",
    "Website mình bị lỗi thanh toán, cần thuê người sửa trong tuần này. Bạn nào nhận fix cho xin báo giá.",
    "Muốn làm CRM nội bộ, tìm đơn vị triển khai trọn gói. Không phải tuyển lập trình viên làm ở công ty.",
    "Tìm designer làm bộ hình quảng cáo cho một chiến dịch, trả phí theo bộ ảnh. Có brief sẵn.",
    "Cần mua phần mềm quản lý kho đã có sẵn, bên nào có demo cho mình xem với.",
    "Mình cần đội tích hợp API kế toán vào hệ thống ERP đang sử dụng, xin báo giá theo hạng mục.",
    "Ai nhận thiết kế menu quán cà phê không, mình gửi nội dung và nhờ làm file in.",
    "Có dev nào viết phần mềm theo yêu cầu không ạ, mình có đặc tả và ngân sách dự án, làm remote được.",
]
LONG_RECRUITMENT_ROLES = [
    ("Chuyên viên Content Marketing", "Viết nội dung website, nghiên cứu từ khóa, phối hợp đội marketing và cập nhật bài viết cho khách hàng."),
    ("Nhân viên SEO", "Kiểm tra website, nghiên cứu từ khóa, theo dõi hiệu quả tìm kiếm và phối hợp với đội nội dung."),
    ("Lập trình viên PHP", "Phát triển website doanh nghiệp bằng PHP, bảo trì mã nguồn và tham gia các dự án của phòng kỹ thuật."),
    ("Designer UI/UX", "Thiết kế giao diện web và app, tạo prototype, cập nhật design system cho các sản phẩm nội bộ."),
    ("Nhân viên quản trị website", "Cập nhật tin bài, thông tin sản phẩm và chăm sóc nội dung trên website của công ty."),
    ("Kỹ sư phần mềm", "Xây dựng CRM, phần mềm quản lý kho và tích hợp API trong đội sản phẩm, phối hợp với BA và QA."),
    ("Chuyên viên tư vấn ERP", "Khảo sát quy trình, cấu hình phần mềm quản trị và đào tạo người dùng cho các dự án khách hàng."),
    ("Nhân viên hỗ trợ ứng dụng", "Tiếp nhận yêu cầu hỗ trợ, hướng dẫn sử dụng app và chuyển lỗi phần mềm đến nhóm phát triển."),
    ("3D Artist", "Dựng nhân vật, environment và animation trong đội thiết kế game, phối hợp cùng các artist khác."),
    ("Thiết kế đồ họa", "Thiết kế logo, banner, catalogue và hình ảnh truyền thông cho thương hiệu của công ty."),
    ("Kỹ sư Automation", "Viết tool tự động hóa, tối ưu workflow và hỗ trợ tích hợp hệ thống trong đội công nghệ."),
    ("QA Engineer", "Viết test case, kiểm tra website bán hàng và ứng dụng quản lý theo yêu cầu của đội sản phẩm."),
    ("Business Analyst", "Làm rõ yêu cầu CRM, ERP, viết tài liệu nghiệp vụ và hỗ trợ team dev trong quá trình triển khai."),
    ("Chuyên viên Marketing", "Quản lý fanpage, phối hợp triển khai website, viết kịch bản quảng cáo và theo dõi chiến dịch."),
    ("Mobile Developer", "Phát triển app Android và iOS, tích hợp API và phối hợp kiểm thử với đội QA."),
    ("Nhân viên triển khai phần mềm", "Cài đặt ứng dụng, hướng dẫn khách hàng sử dụng hệ thống và hỗ trợ nghiệm thu các hạng mục."),
]
for role, tasks in LONG_RECRUITMENT_ROLES:
    SYNTHETIC_RECRUITMENT.append(
        f"[THÔNG BÁO TUYỂN DỤNG] Công ty cần bổ sung vị trí {role} vào đội ngũ nhân sự chính thức.\n"
        f"Mô tả công việc: {tasks}\n"
        "Yêu cầu ứng viên: Có kiến thức nền tảng đúng chuyên môn, giao tiếp rõ ràng, chủ động và phối hợp tốt với đồng nghiệp. "
        "Ưu tiên người đã có kinh nghiệm ở vị trí tương đương; nhân sự mới được đào tạo theo quy trình của công ty.\n"
        "Quyền lợi: Lương cố định hàng tháng theo năng lực, thưởng hiệu quả công việc, phụ cấp ăn trưa và bảo hiểm theo quy định. "
        "Thời gian làm việc: giờ hành chính từ thứ Hai đến thứ Sáu, làm việc tại văn phòng, có chế độ nghỉ phép.\n"
        "Bạn quan tâm vui lòng gửi CV, hồ sơ kinh nghiệm và mức lương mong muốn cho phòng nhân sự để sắp xếp phỏng vấn. "
        "Đây là vị trí nhân viên trong team, không tìm đơn vị cung cấp dịch vụ theo dự án."
    )
SYNTHETIC_OTHER = [
    "Dựng mô hình 3D là quá trình thể hiện hình khối bằng phần mềm. Có nhiều phong cách như Low Poly, Mid Poly và High Poly. Tùy yêu cầu của sản phẩm, nghệ sĩ sẽ chọn số polygon và cách tạo vật liệu phù hợp. Bài viết chia sẻ kiến thức cơ bản cho người mới tìm hiểu, không phải lời tìm người làm dự án.",
    "Một thế giới game gồm nhân vật, bản đồ, cây cối và các vật phẩm. Thiết kế các thành phần đồng bộ giúp trải nghiệm đẹp hơn. Topology, texture và ánh sáng đều có vai trò riêng. Mọi người chia sẻ kinh nghiệm học 3D của mình bên dưới nhé.",
    "Khi thiết kế 3D kiến trúc, người học cần hiểu tỷ lệ không gian, ánh sáng, vật liệu và cách bố trí công năng. Việc dựng phối cảnh giúp hình dung trước công trình. Đây là bài chia sẻ lý thuyết về một công cụ thiết kế, không có dự án cần thuê bên ngoài.",
    "Nhân vật trong game thường được dựng hình, tạo texture, rigging rồi mới làm animation. Các giai đoạn cần liên kết tốt để nhân vật chuyển động ổn định. Bài này ghi lại kiến thức mình học được để mọi người tham khảo.",
    "Website bán hàng nên tải nhanh, hỗ trợ điện thoại và có thông tin sản phẩm đầy đủ. Mọi người có kinh nghiệm chọn hosting chia sẻ thêm để mình hiểu với nhé. Mình đang tìm hiểu lý thuyết.",
    "Các bạn mới tham gia nhóm nhớ đọc nội quy và giới thiệu ngắn về lĩnh vực đang học. Chúc mọi người kết nối với nhau và trao đổi kinh nghiệm lập trình hữu ích.",
    "Java và Python khác nhau ở cú pháp, cách triển khai và hệ sinh thái thư viện. Bài viết hôm nay giải thích các điểm khác biệt cơ bản và gợi ý tài liệu học miễn phí.",
    "Tổ chức khảo sát trải nghiệm người dùng phần mềm quản lý, mong mọi người điền biểu mẫu góp ý. Kết quả chỉ tổng hợp thống kê, không đặt hàng một dự án mới.",
    "Mình đã làm xong app thử nghiệm, mời mọi người sử dụng thử và góp ý lỗi giao diện. Chưa có yêu cầu thuê người phát triển hay quảng bá bán dịch vụ.",
    "Mọi người cho mình hỏi học thiết kế UI/UX nên bắt đầu từ công cụ nào? Mình muốn tìm tài liệu và lời khuyên để tự học.",
    "Hôm nay chia sẻ kiến thức về API và webhook. API được gọi chủ động, webhook gửi thông báo khi có sự kiện. Đây là bài giải thích khái niệm.",
    "Cảm ơn các thành viên đã giúp đỡ nhau trong nhóm. Tuần này có bài chia sẻ kinh nghiệm quản lý dự án phần mềm để mọi người cùng thảo luận.",
]
SYNTHETIC_SELLERS = [
    "Mình cần tìm job freelance thiết kế web để nhận làm thêm, bạn nào có dự án giới thiệu cho mình nhé.",
    "Đang tìm khách cần làm landing page. Mình nhận thiết kế trên Figma, gửi portfolio cho bạn nào quan tâm.",
    "Dev freelancer tìm việc online, nhận code website và app theo yêu cầu. Ai có đầu việc inbox mình.",
    "Mình đang trống lịch, cần nhận thêm job thiết kế banner, logo và hình sản phẩm, giá theo khối lượng.",
    "Tìm dự án web để nhận làm, mình có kinh nghiệm PHP và React, khách cần triển khai liên hệ mình.",
    "Em đang cần việc freelance 3D, nhận dựng model và render theo yêu cầu khách hàng. Có portfolio để tham khảo.",
    "Mình cần tìm đối tác có khách làm website để hợp tác. Bên mình trực tiếp nhận thiết kế và code, chia hoa hồng giới thiệu.",
    "Sinh viên IT tìm job lập trình online, nhận làm tool nhỏ, sửa lỗi web và tích hợp API. Ai có việc nhắn mình báo phí.",
    "Em đang tìm việc làm thiết kế từ xa. Anh chị có nhu cầu làm poster hoặc catalogue thì gửi brief cho em nhé.",
    "Cần thêm khách đặt thiết kế website, mình nhận làm theo yêu cầu, hỗ trợ bảo trì sau bàn giao.",
    "Nhận job designer freelance online, gửi mẫu sản phẩm cho khách xem trước và báo giá từng hạng mục.",
    "Tìm công việc code tự do vào cuối tuần, mình có thể viết app quản lý và website cho anh chị cần sử dụng.",
]
SYNTHETIC_RECRUITMENT_TEST = [
    "[Tuyển nhân sự] Agency cần một bạn viết bài cho website làm toàn thời gian. Công việc nghiên cứu nội dung và cập nhật các trang của khách hàng. Lương tháng theo năng lực, có phụ cấp. Ứng viên gửi CV và vài bài đã viết cho HR.",
    "Công ty tuyển nhân viên lập trình C# vào phòng kỹ thuật. Nhiệm vụ bảo trì ứng dụng quản lý, phối hợp tester và triển khai chức năng mới. Có lương tháng và bảo hiểm. Bạn phù hợp gửi hồ sơ để phỏng vấn tại văn phòng.",
    "TUYỂN CONTENT CREATOR. Team cần bổ sung người sáng tạo nội dung cho website và fanpage. Yêu cầu viết rõ ràng, làm việc giờ hành chính. Quyền lợi gồm lương cố định, thưởng KPI và phụ cấp ăn trưa. Gửi CV cùng sản phẩm mẫu để ứng tuyển.",
    "Mở vị trí kỹ sư phần mềm trong đội sản phẩm của công ty. Công việc viết API và tích hợp CRM, hợp đồng lao động lâu dài. Lương hàng tháng, chế độ nghỉ phép. Nộp CV cho bộ phận tuyển dụng.",
    "Studio cần tuyển nhân viên thiết kế 3D chính thức. Dựng nhân vật, vật liệu và animation cho sản phẩm của studio. Có mentor, thời gian thử việc và lương cố định. Hồ sơ gồm CV và portfolio, phỏng vấn tại công ty.",
    "Tuyển chuyên viên triển khai hệ thống bán hàng vào đội dịch vụ khách hàng. Làm việc toàn thời gian, nhận lương và phúc lợi của công ty. Anh chị có kinh nghiệm phần mềm ERP gửi hồ sơ ứng tuyển cho phòng nhân sự.",
]


def main():
    rows = json.loads((ROOT / ".local/laya-training/extracted.json").read_text(encoding="utf-8"))
    groups = {}
    for row in rows:
        groups.setdefault(row["content_group"], []).append(row)
    if len(groups) != 102:
        raise ValueError("Nguồn khác bộ 102 mẫu đã đọc; cần gán nhãn lại.")
    samples = []
    for index, items in enumerate(groups.values()):
        label = "service_request" if index in REQUESTS else "other" if index in OTHER else "recruitment" if index in RECRUITMENT else "self_promotion"
        reason = NOTES.get(index) or {"service_request":"Tác giả nêu nhu cầu của mình và tìm người thực hiện/cung cấp.","other":"Chia sẻ, thảo luận hoặc hỏi thông tin; không có yêu cầu thuê hay chào bán rõ.","self_promotion":"Tác giả giới thiệu/chào cung cấp dịch vụ hoặc sản phẩm của mình.","recruitment":"Tuyển nhân sự vào đội ngũ."}[label]
        for item in items:
            item.update(label=label, reason=reason, label_source="assistant_review_of_user_text", review_index=index)
        samples.append({**items[0], "source_ids":[r["id"] for r in items], "origin":"user_paste", "needs_review":index in {17,72,95}, "split":"train"})
    # Merge close templates before splitting; copies of the same message cannot cross partitions.
    for i, sample in enumerate(samples):
        normalized = " ".join(sample["text"].lower().split())
        for previous in samples[:i]:
            if previous["label"] == sample["label"] and difflib.SequenceMatcher(None, normalized, " ".join(previous["text"].lower().split()), autojunk=False).ratio() > .85:
                sample["content_group"] = previous["content_group"]
                break
    families = {}
    for sample in samples:
        families.setdefault(sample["content_group"], []).append(sample)
    rng = random.Random(411)
    for label in QUESTION["criteria"]:
        choices = [key for key, items in families.items() if items[0]["label"] == label and not any(p["needs_review"] for p in items)]
        rng.shuffle(choices)
        ntest = max(1, round(len(choices) * .2))
        nval = max(1, round(len(choices) * .15)) if len(choices)>3 else 0
        for i, key in enumerate(choices):
            for sample in families[key]:
                sample["split"] = "test" if i<ntest else "validation" if i<ntest+nval else "train"
    for sample in samples:
        if sample["needs_review"]:
            sample["split"] = "review_only"
        elif sample["label"] == "recruitment":
            # The sole real recruitment example must teach the model this user's domain.
            sample["split"] = "train"
    for label,texts in (("recruitment",SYNTHETIC_RECRUITMENT),("service_request",SYNTHETIC_REQUESTS),("other",SYNTHETIC_OTHER),("self_promotion",SYNTHETIC_SELLERS)):
        for i,text in enumerate(texts):
            samples.append({"id":f"synthetic-{label}-{i:02d}","text":text,"label":label,"origin":"synthetic_assistant",
                            "content_group":normalize_group(text),"split":"validation" if i>=len(texts)-4 else "train",
                            "reason":"Mẫu bổ sung tự soạn, không phải bài Facebook thực tế.","needs_review":False})
    for i,text in enumerate(SYNTHETIC_RECRUITMENT_TEST):
        samples.append({"id":f"synthetic-recruitment-test-{i:02d}","text":text,"label":"recruitment","origin":"synthetic_assistant",
                        "content_group":normalize_group(text),"split":"test","reason":"Mẫu tuyển dụng tự soạn, chỉ dùng kiểm tra.","needs_review":False})
    output = ROOT / "data/laya"
    output.mkdir(parents=True, exist_ok=True)
    for name,items in (("posts_labeled.jsonl",rows),("post_type_dataset.jsonl",samples)):
        (output/name).write_text("".join(json.dumps(item,ensure_ascii=False)+"\n" for item in items),encoding="utf-8")
    (output/"post_type_question.json").write_text(json.dumps({"post_type":QUESTION},ensure_ascii=False,indent=2),encoding="utf-8")
    summary={"posts":len(rows),"user_content_samples":len(groups),"merged_user_families":len(families),"labels":dict(collections.Counter(r["label"] for r in rows)),"training_samples":dict(collections.Counter((r['split']+':'+r['origin']) for r in samples)),"synthetic_samples":len(samples)-len(groups),"label_source":"Assistant-reviewed source text, not user-certified labels"}
    (output/"dataset_summary.json").write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding="utf-8")
    lines=["# Dữ liệu gán nhãn từ dashboard DK-Tech", "", "Nguồn: file người dùng gửi ngày 11/10/2026. Nhãn do trợ lý đọc nội dung; các status Laya cũ không được dùng làm đáp án.", "", "Mẫu bổ sung tự soạn được ghi origin=synthetic_assistant. Mẫu chưa rõ giữ riêng, không dùng để train.", "", "| STT | ID bài đại diện | Số bài lặp | Nhãn | Nội dung |", "|---|---|---:|---|---|"]
    for i,items in enumerate(groups.values()):
        r=items[0]
        preview=r['text'][:140].replace('|','/').replace('\n',' ')
        lines.append(f"| {i+1} | {r['id']} | {len(items)} | {r['label']} | {preview} |")
    (output/"LABELS.md").write_text("\n".join(lines)+"\n",encoding="utf-8")
    print(json.dumps(summary,ensure_ascii=False))


if __name__ == "__main__":
    main()
