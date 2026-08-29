const userTableBody = document.getElementById('userTableBody');
const userSelect = document.getElementById('userSelect');
const newPasswordInput = document.getElementById('newPassword');
const confirmPasswordInput = document.getElementById('confirmPassword');
const passwordForm = document.getElementById('passwordForm');
const statusMessage = document.getElementById('statusMessage');

function setStatus(message, isError = false) {
  statusMessage.textContent = message || '';
  statusMessage.style.color = isError ? '#b42318' : '#087443';
}

async function loadUsers() {
  const response = await fetch('/api/users', {
    method: 'GET',
    credentials: 'same-origin',
    headers: { Accept: 'application/json' },
  });
  const data = await response.json().catch(() => ({}));

  if (!response.ok) {
    throw new Error(data.message || 'ไม่สามารถโหลดรายชื่อผู้ใช้ได้');
  }

  userTableBody.innerHTML = '';
  userSelect.innerHTML = '';

  data.forEach((user) => {
    const row = document.createElement('tr');
    row.innerHTML = `
      <td style="padding:10px; border-bottom:1px solid #d0d7de;">${user.username}</td>
      <td style="padding:10px; border-bottom:1px solid #d0d7de;">${user.role || '-'}</td>
      <td style="padding:10px; border-bottom:1px solid #d0d7de;">${user.branch || '-'}</td>
    `;
    userTableBody.appendChild(row);

    const option = document.createElement('option');
    option.value = user.username;
    option.textContent = user.username;
    userSelect.appendChild(option);
  });
}

window.authReady.then(async (user) => {
  if (user.role !== 'admin') {
    window.location.href = '/';
    return;
  }

  try {
    await loadUsers();
  } catch (error) {
    setStatus(error.message, true);
  }
}).catch((error) => {
  setStatus(error.message || 'กรุณาเข้าสู่ระบบอีกครั้ง', true);
});

passwordForm.addEventListener('submit', async (event) => {
  event.preventDefault();

  const username = userSelect.value;
  const newPassword = newPasswordInput.value;
  const confirmPassword = confirmPasswordInput.value;

  if (!username) {
    setStatus('กรุณาเลือกบัญชีผู้ใช้งาน', true);
    return;
  }

  if (!newPassword || !confirmPassword) {
    setStatus('กรุณากรอกรหัสผ่านใหม่และยืนยันรหัสผ่าน', true);
    return;
  }

  if (newPassword !== confirmPassword) {
    setStatus('รหัสผ่านใหม่และยืนยันรหัสผ่านไม่ตรงกัน', true);
    return;
  }

  const response = await fetch('/api/users/change-password', {
    method: 'POST',
    credentials: 'same-origin',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      username,
      new_password: newPassword,
      confirm_password: confirmPassword,
    }),
  });
  const data = await response.json().catch(() => ({}));

  if (!response.ok) {
    setStatus(data.message || 'เปลี่ยนรหัสผ่านไม่สำเร็จ', true);
    return;
  }

  passwordForm.reset();
  setStatus(data.message || 'เปลี่ยนรหัสผ่านเรียบร้อยแล้ว');
});
