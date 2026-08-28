# ระบบบันทึกและสรุปการแปรรูปสินค้า

## เปิดใช้งาน

ดับเบิลคลิก `start.bat` ใส่ OpenAI API key ในหน้าต่างสีดำ แล้วโปรแกรมจะเปิด
`http://localhost:8088` ให้อัตโนมัติ ตัวอักษรของ key จะถูกซ่อนและจะไม่ถูกบันทึกลงไฟล์

ข้อมูลบันทึกถาวรอยู่ใน `processing.db` (สร้างอัตโนมัติเมื่อเปิดครั้งแรก)

## Login สำหรับทดสอบในเครื่อง

- Admin: `admin` / `admin123`
- Manager บางบัวทอง: `manager_bangbuathong` / `manager123`
- Manager ตรัง: `manager_trang` / `manager123`
- Manager หลังสวน: `manager_langsuan` / `manager123`

รหัสเหล่านี้ใช้เฉพาะ Local development ต้องเปลี่ยนผ่าน environment variables ก่อน Production ดูรายละเอียดใน `PRODUCTION.md`

## Database

ระบบใช้ SQLite ในเครื่องเพื่อเก็บข้อมูลเดิมถาวร และรองรับ PostgreSQL เมื่อกำหนด `DATABASE_URL`
สคริปต์ `migrate_sqlite_to_postgres.py` ใช้ย้ายข้อมูลเดิมแบบไม่ลบไฟล์ SQLite

## เปิดการอ่านฉลากด้วย AI

หรือจะตั้งค่า environment variable `OPENAI_API_KEY` ก่อนเปิดโปรแกรมเองก็ได้ เช่นใน PowerShell:

```powershell
$env:OPENAI_API_KEY="ใส่ API key ที่นี่"
.\.venv\Scripts\python.exe .\pork-processing-app\app.py
```

หากไม่ได้ตั้ง API key โปรแกรมยังใช้ตรวจรูปและกรอกชื่อ/น้ำหนักด้วยมือได้ตามปกติ รายการที่ข้อมูลไม่ครบจะไม่ถูกรวมยอดหรือบันทึก
