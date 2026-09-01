(()=>{
  function rowsFromPage(){
    const preview=document.querySelectorAll('#orderSummary .summary-order-row');
    if(preview.length)return [['รายการสินค้า','จำนวน/น้ำหนัก'],...[...preview].map(row=>[...row.children].map(c=>c.innerText.trim()))];
    const report=[...document.querySelectorAll('#report .reportrow,#summary .sumrow')].filter(x=>x.offsetParent!==null);
    if(report.length)return report.map(row=>[...row.children].map(c=>c.innerText.trim()));
    const table=[...document.querySelectorAll('table')].find(t=>t.offsetParent!==null);
    if(!table)return [];
    return [...table.querySelectorAll('tr')].map(tr=>[...tr.querySelectorAll('th,td')].map(cell=>cell.querySelector('input,select')?.value||cell.innerText.trim()));
  }
  function metadata(){const date=document.querySelector('input[type=date]'),branch=document.querySelector('select[id*=Branch],select[id*=branch]');return [['วันที่',date?.value||''],['สาขา',branch?.selectedOptions?.[0]?.text||''],['วันที่ Export',new Date().toLocaleString('th-TH')]]}
  async function exportExcel(){const rows=rowsFromPage();if(!rows.length)return alert('ไม่มีข้อมูลสำหรับ Export');const title=document.querySelector('h1')?.innerText||document.title,date=document.querySelector('input[type=date]')?.value||new Date().toISOString().slice(0,10),slug=location.pathname.split('/').pop()?.replace('.html','')||'processing-summary';const response=await fetch('/api/export-xlsx',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({title,metadata:metadata(),rows,filename:`${slug}-${date}.xlsx`})});if(!response.ok){const error=await response.json();return alert(error.message||'Export ไม่สำเร็จ')}const blob=await response.blob(),url=URL.createObjectURL(blob),link=document.createElement('a');link.href=url;link.download=`${slug}-${date}.xlsx`;link.click();URL.revokeObjectURL(url)}
  function init(){if(document.querySelector('.report-actions'))return;const main=document.querySelector('main');if(!main)return;const bar=document.createElement('div');bar.className='report-actions no-print';bar.innerHTML='<button class="secondary" type="button">Export Excel</button><button class="secondary" type="button">Print</button>';bar.children[0].onclick=exportExcel;bar.children[1].onclick=()=>window.print();main.prepend(bar)}
  document.readyState==='loading'?document.addEventListener('DOMContentLoaded',init):init();
})();
