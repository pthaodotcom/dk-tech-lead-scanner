# Kết quả train đầu phân loại trên encoder Laya

Nguồn: 175 bài trong file dashboard người dùng gửi ngày 11/10/2026. Nhãn do trợ lý đọc nội dung, chưa được xác nhận độc lập.

## Dữ liệu và phương pháp

- 135 bài tự quảng cáo, 27 bài tìm dịch vụ/người làm, 12 bài khác, 1 bài tuyển dụng nhân viên.
- Gộp nội dung lặp còn 102 mẫu; 3 mẫu chưa rõ được giữ riêng và không học.
- 82 mẫu bổ sung tự soạn được ghi nguồn rõ. Tập học: 66 mẫu thật + 60 mẫu tự soạn; validation: 14 thật + 16 tự soạn; kiểm tra: 19 thật + 6 tự soạn.
- Đầu phân loại bốn nhãn dùng encoder Laya đóng băng, kết hợp TF-IDF từ/cặp từ xây riêng từ tập học. Chỉ cập nhật trọng số đầu phân loại; không cập nhật encoder hoặc các đầu xét dịch vụ/an toàn gốc.
- Các bài gần giống được giữ trong cùng một phần dữ liệu để tránh bản sao xuất hiện cả ở tập học và tập kiểm tra.

## Phép so sánh trên 19 bài thật

| Chỉ số | Laya gốc với câu hỏi tiếng Việt | Đầu phân loại đã học |
|---|---:|---:|
| Phân loại đúng | 11/19 (57.9%) | 17/19 (89.5%) |
| Bài quảng cáo nhận đúng | 11/12 | 12/12 |
| Bài tìm dịch vụ nhận đúng | 0/5 | 4/5 |
| Bài không phải nhu cầu bị nhận thành nhu cầu | 2 | 0 |

Ngưỡng tin cậy loại bài để đủ điều kiện tự động comment: 90%, chọn từ validation. Trong tập kiểm tra, 3/5 bài tìm dịch vụ qua ngưỡng này; các bài còn lại vẫn giữ để xem lại. Nhóm dịch vụ và an toàn vẫn phải qua điều kiện riêng của model gốc.

## Giới hạn của kết quả

- Tập 19 bài thật nhỏ và đã được xem kết quả trong các lần thử kiến trúc; đây là phép đánh giá thăm dò, không phải số đo độc lập về độ chính xác ngoài thực tế.
- Bài tuyển dụng thật duy nhất được đưa vào tập học. 6/6 mẫu tuyển dụng tự soạn giữ riêng được nhận đúng; chưa có tập bài tuyển dụng thật độc lập để đo khả năng tổng quát.
- Hai bài thật còn nhầm trong tập kiểm tra:

| ID bài | Nhãn đã gán | Model dự đoán |
|---|---|---|
| 1851164486129503 | service_request | other |
| 3379986638872983 | other | self_promotion |

## Áp dụng và chứng cứ

- Đầu phân loại có 393,476 tham số được huấn luyện; vocabulary TF-IDF có 1533 mục.
- SHA-256 trọng số: `5bc1339a097dd1d1102304a09515101d6b427bbc5c5be25ed5eea2932a1cf407`.
- Model đã được xuất thành release bất biến trong `.local/laya-training/releases/`; con trỏ active chọn bản đạt phép kiểm tra cục bộ.
- `report.json` giữ số liệu, confusion matrix và lịch sử loss; `predictions.jsonl` giữ dự đoán từng mẫu.
- Kiểm tra tích hợp 5 nội dung nguồn: quảng cáo 3D, khách làm web B2B, quảng cáo API, thuê freelancer làm Key Visual, tuyển nhân viên Content SEO. Cả 5 nhận đúng loại; quảng cáo/tuyển dụng không đủ điều kiện tự động comment.
- 5 kiểm tra hồi quy cho điều kiện comment đã qua; JS và Python đã kiểm tra cú pháp.

Tài liệu kỹ thuật tham khảo: [Laya fine-tuning](https://github.com/NandhaKishorM/laya/blob/main/docs/finetune.md).
