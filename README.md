# DK-Tech Lead Scanner

Tool Windows cho Page **DK-Tech**: quét bài mới trong group Facebook, lọc bằng rule,
Laya multilingual phân loại nhu cầu/an toàn, Qwen3 1.7B viết comment và extension
Chrome gửi bằng thao tác trên giao diện Facebook.

Dashboard: `http://127.0.0.1:9350/`.
Page được cấu hình: `61593769810301`. Số liên hệ trong comment: `0342391808`.

## Cài trên máy công ty

### 1. Chuẩn bị

Cài các phần mềm sau:

- [Python 3.13 cho Windows, bản 64-bit](https://www.python.org/downloads/windows/).
  Chọn phiên bản **3.13**, cài Python launcher và bật **Add python.exe to PATH**.
  Bộ thư viện đã được chốt theo môi trường Python 3.13 đang chạy của tool.
- [Google Chrome](https://www.google.com/chrome/).
- [Ollama cho Windows](https://ollama.com/download/windows).

Máy cần Internet để cài thư viện, tải model lần đầu và truy cập Facebook.
Không cần Node.js để sử dụng tool thông thường.

### 2. Lấy mã nguồn

Đăng nhập tài khoản GitHub có quyền xem repo này, chọn **Code → Download ZIP**,
giải nén vào thư mục riêng, ví dụ `D:\Tools\dk-tech-lead-scanner`.
Giữ nguyên các thư mục con; không chạy trực tiếp trong file ZIP.

Nếu đã cài Git, có thể clone:

```powershell
git clone https://github.com/pthaodotcom/dk-tech-lead-scanner.git
cd dk-tech-lead-scanner
```

### 3. Cài tool một lần

Double-click **`setup-tool.cmd`** và chờ thông báo `Setup complete`.
Script sẽ:

1. Tạo môi trường `.venv` bằng Python 3.13 64-bit.
2. Cài thư viện từ `requirements.txt`, theo phiên bản trong `requirements-lock.txt`.
3. Kiểm tra Ollama và tải `qwen3:1.7b` nếu chưa có.
4. Tải/nạp Laya multilingual nếu chưa có cache hoàn chỉnh; nếu có thì dùng cache.
5. Tạo shortcut **DK Tech Lead Scanner** trên Desktop.

Máy mới tải model riêng một lần. Model và cache ở máy cũ không nằm trong repo.
Bước cài đặt không quét Facebook hoặc gửi comment.

Có thể chạy từ PowerShell:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\setup-tool.ps1
```

### 4. Nạp extension và đăng nhập Page

1. Mở Chrome, đăng nhập Facebook và chuyển sang **Page DK-Tech**.
2. Mở `chrome://extensions/`, bật **Developer mode / Chế độ dành cho nhà phát triển**.
3. Chọn **Load unpacked / Tải tiện ích đã giải nén**.
4. Chọn thư mục **`extension\dk-tech-lead-scanner`** trong mã nguồn vừa tải.
5. Nạp lại các tab Facebook. Ghim extension **DK-Tech Lead Scanner** nếu cần.
6. Double-click **`start-tool.cmd`** hoặc shortcut trên Desktop để mở dashboard.

Launcher mở profile Chrome `Default`. Hãy đăng nhập Page và nạp extension trong
đúng profile này; kiểm tra avatar profile ở góc Chrome nếu máy có nhiều profile.
Không phải nạp extension lại mỗi lần chạy; giữ nguyên thư mục mã nguồn sau khi cài.

### 5. Khởi tạo danh sách group trên máy mới

Database mới chưa có danh sách group hoặc lịch sử gửi.

1. Trong Facebook, mở **Nhóm của bạn / nhóm đã tham gia** và thay đổi sắp xếp
   để extension ghi nhận request danh sách group.
2. Giữ tab đó mở. Mở thêm một group Page truy cập được, cuộn tải thêm bài hoặc
   đổi sắp xếp để ghi nhận request feed.
3. Mở extension và bấm **Quét group và bài**.
4. Vào dashboard → cấu hình nhóm, chọn nhóm được quét và nhóm được phép gửi.
5. Cấu hình từ khóa giữ lại/loại bỏ theo nhu cầu.

Sau khi đã lưu danh sách group, quét ngầm tự mở tab tác vụ và tải feed.

### 6. Bật tự động

- Bấm **Bật quét ngầm** để đọc bài định kỳ; không cần giữ popup mở.
- Bấm **Thử gửi 1 comment rồi dừng** để thử luồng gửi thật một lần.
- Bấm **Bật gửi ngầm** để vận hành liên tục theo giới hạn đã đặt.
- Xem nội dung, trạng thái, ID comment trong **Comment đã xử lý** trên dashboard.
- Khi kết thúc, bấm **Dừng gửi ngầm**, **Dừng quét ngầm**, rồi **Dừng tool**
  trên dashboard.

Mặc định nghỉ 10 phút giữa các vòng quét và giữa comment; số comment/lượt là 3,
giới hạn 4 comment/giờ và 20 comment/ngày. Có thể chỉnh trong popup.
Mỗi group còn có giới hạn 3 comment/24 giờ ở backend.

Một bài chỉ được tự gửi khi thuộc group cho phép gửi, đọc được ngày đăng trên
Facebook và không quá 24 giờ, qua rule, được Laya đánh dấu phù hợp với độ tin cậy
ít nhất 60% cho các câu hỏi phân loại, và chưa có lịch sử xếp hàng/gửi.
Độ tin cậy của model không phải tỷ lệ chính xác đã được kiểm chứng trên dữ liệu này.
Nếu đã nhấn gửi mà kết quả chưa xác minh được, tool lưu lần thử và không gửi lại
cùng nội dung. Không dùng lại bài bị khóa để ép chạy thử.

## Chuyển từ máy cá nhân sang máy công ty

Dừng quét và gửi trên máy cũ trước khi bật trên máy mới nếu chỉ muốn một máy gửi.
Mỗi máy dùng database riêng nên lịch sử chống trùng không tự đồng bộ qua GitHub.

Để giữ nhóm, rule và lịch sử cũ: dừng backend trên cả hai máy rồi chép riêng file
`.local\dk-tech-lead-scanner\scanner.sqlite3` từ máy cũ vào cùng vị trí trong
thư mục tool trên máy mới. Sau đó mở tool lại. File này có dữ liệu Facebook;
giữ trong kênh chuyển file riêng, không commit lên GitHub.

Đăng nhập Facebook lại trên máy công ty. Không cần đưa cookie/token vào tool.

## Chạy nền và giới hạn hiện tại

Chrome → Settings → System → bật **Continue running background apps when
Google Chrome is closed**. Tool dùng cửa sổ tác vụ thu nhỏ khi quét/gửi.
Máy vẫn phải bật, không Sleep và backend phải còn chạy; không chọn Exit Chrome
hoặc kết thúc tiến trình.

**Bản này chưa triển khai VPS. Tắt máy thì tool dừng.** Muốn tiếp tục khi máy cá
nhân tắt cần cài và đăng nhập tool trên một máy/VPS luôn bật. Repo này cung cấp
bộ cài Windows cho máy công ty.

## Khi Facebook đổi cơ chế

Nạp lại extension và tab group, tải thêm bài rồi mở **F12 → Console**.
Dán nội dung [diagnostics/scan_debug.js](diagnostics/scan_debug.js) để in và sao
chép báo cáo. Báo cáo gồm phiên bản, kích thước cửa sổ, tên query, `doc_id`,
tên biến và cảnh báo tương thích; không gồm cookie/token/request body/giá trị biến.
Nếu chưa ghi nhận feed, đổi sắp xếp hoặc tải thêm bài rồi lấy báo cáo lại.

Log giúp tìm phần cần sửa. Extension vẫn cần được cập nhật nếu request/parser
không còn tương thích. `PARTIAL` nghĩa là còn trang chưa quét sau giới hạn hoặc
có group chưa hoàn tất; không đồng nghĩa đã quét đủ tất cả bài.

## Lỗi cài đặt thường gặp

| Hiện tượng | Cách xử lý |
| --- | --- |
| Không tìm thấy Python 3.13 | Cài Python 3.13 64-bit và launcher, mở lại terminal rồi chạy setup. Kiểm tra bằng `py -3.13 --version`. |
| Không gọi được Ollama | Mở Ollama, kiểm tra `http://127.0.0.1:11434/api/tags`, chạy setup lại. |
| Không tải được model/thư viện | Kiểm tra kết nối từ máy công ty tới PyPI, Hugging Face và Ollama; xem lỗi trong cửa sổ setup. |
| Quét ngầm báo chưa có group | Làm bước khởi tạo danh sách group lần đầu. |
| Chưa bắt được request feed | Reload tab group, đổi sắp xếp/tải thêm bài và lấy báo cáo Console. |
| Tab không dùng Page DK-Tech | Chuyển Facebook sang đúng Page, reload tab rồi quét lại. |
| Backend không kết nối | Chạy `start-tool.cmd`, mở `http://127.0.0.1:9350/health` để kiểm tra. |

## Cập nhật tool

Dừng gửi/quét và backend trước khi thay mã nguồn. Nếu dùng Git, chạy `git pull`.
Nếu tải ZIP, chép mã nguồn mới vào thư mục đang dùng và giữ `.local`, `.venv`.
Chạy lại `setup-tool.cmd` khi thư viện thay đổi, bấm **Reload** ở
`chrome://extensions/`, reload tab Facebook rồi mở `start-tool.cmd`.

## Cấu trúc mã nguồn

- `app/`: backend Python, SQLite, rule, Laya, Qwen và dashboard.
- `extension/dk-tech-lead-scanner/`: extension đang sử dụng; quét bằng request
  trong phiên Chrome, gửi comment bằng UI Driver.
- `scripts/warmup-laya.py`: chuẩn bị model cho cài đặt.
- `scripts/*.mjs`: công cụ phát triển qua Chrome CDP, không cần chạy khi cài thông thường.
- `diagnostics/`: script chẩn đoán và bản thử nghiệm cũ; chỉ nạp extension sản phẩm
  ở đường dẫn trên, không cài `diagnostics/facebook-request-probe` để vận hành.
- `requirements-lock.txt`: phiên bản thư viện lấy từ môi trường đang hoạt động.
- `.local/`, `.venv/`, database, cache, shortcut và log không được đưa lên GitHub.

Kiểm tra cú pháp extension khi phát triển (cần Node.js):

```powershell
node --check extension/dk-tech-lead-scanner/background.js
node --check extension/dk-tech-lead-scanner/probe.js
node --check extension/dk-tech-lead-scanner/popup.js
```
