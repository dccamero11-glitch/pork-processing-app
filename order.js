const ORDER_PRODUCTS=[]; const ORDER_CATALOG={"หมู":[],"ไก่":[]}; let currentOrderCategory="หมู";
const state={quantities:{},pendingRequestId:null,pendingSignature:null},$=id=>document.getElementById(id),esc=v=>String(v).replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
const items=()=>ORDER_PRODUCTS.map(product_name=>({product_name,quantity:Number(state.quantities[product_name]||0),unit:"กก."})).filter(x=>x.quantity>0);
async function api(url,opt={}){const r=await fetch(url,{headers:{"Content-Type":"application/json"},...opt}),type=r.headers.get("content-type")||"",text=await r.text();let j={};if(text&&type.includes("application/json")){try{j=JSON.parse(text)}catch{throw Error("เซิร์ฟเวอร์ส่งข้อมูลตอบกลับไม่ถูกต้อง กรุณาลองใหม่")}}else if(text){throw Error("เซิร์ฟเวอร์ส่งข้อมูลตอบกลับไม่ถูกต้อง กรุณาลองใหม่")}if(!r.ok)throw Error(j.message||"บันทึกคำสั่งซื้อไม่สำเร็จ กรุณาลองใหม่");if(!text)throw Error("เซิร์ฟเวอร์ไม่ส่งผลการบันทึกกลับมา กรุณาตรวจสอบประวัติก่อนลองใหม่");return j}
function summary(){const rows=items(),total=rows.reduce((s,x)=>s+x.quantity,0);$("summaryBranch").textContent=$("orderBranch").value||"กรุณาเลือกสาขา";$("orderSummary").innerHTML=rows.length?rows.map(x=>`<div class="summary-order-row"><span>${esc(x.product_name)}</span><strong>${x.quantity.toFixed(2)} ${x.unit}</strong></div>`).join(""):'<div class="empty">ยังไม่มีรายการ</div>';$("totalWeight").textContent=total.toFixed(2)}
function render(){ORDER_PRODUCTS.splice(0,ORDER_PRODUCTS.length,...(ORDER_CATALOG[currentOrderCategory]||[])); const q=$("orderSearch").value.trim().toLowerCase(),products=ORDER_PRODUCTS.filter(x=>x.toLowerCase().includes(q));$("orderRows").innerHTML=products.map((name,i)=>`<tr class="${Number(state.quantities[name])>0?'selected':''}"><td>${i+1}</td><td>${esc(name)}</td><td><input data-product="${esc(name)}" type="number" min="0" step="0.01" inputmode="decimal" value="${esc(state.quantities[name]??'')}" placeholder="0.00"></td><td>กก.</td></tr>`).join("")||'<tr><td colspan="4" class="empty">ไม่พบรายการสินค้า</td></tr>';document.querySelectorAll('[data-product]').forEach(input=>input.oninput=()=>{if(input.value!==''&&Number(input.value)<0)input.value='0';state.quantities[input.dataset.product]=input.value;input.closest('tr').classList.toggle('selected',Number(input.value)>0);summary()})}
function reset(){state.quantities={};$("orderNote").value="";$("orderNotice").innerHTML="";render();summary()}
$("orderSearch").oninput=render;$("clearOrderSearch").onclick=()=>{$("orderSearch").value="";render()};$("orderBranch").onchange=summary;$("clearOrder").onclick=()=>{if(confirm("ล้างข้อมูลคำสั่งซื้อทั้งหมดหรือไม่?"))reset()};
$("saveOrder").onclick=async()=>{const button=$("saveOrder"),branch=$("orderBranch").value,rows=items(),note=$("orderNote").value,total=rows.reduce((s,x)=>s+x.quantity,0);if(!branch)return alert("กรุณาเลือกสาขา");if(!rows.length)return alert("กรุณากรอกสินค้าอย่างน้อย 1 รายการที่มีน้ำหนักมากกว่า 0");if(!confirm(`ยืนยันบันทึกคำสั่งซื้อของสาขา ${branch} น้ำหนักรวม ${total.toFixed(2)} กก. หรือไม่?`))return;const signature=JSON.stringify({branch,note,items:rows});if(state.pendingSignature!==signature){state.pendingSignature=signature;state.pendingRequestId=globalThis.crypto?.randomUUID?.()||`${Date.now()}-${Math.random()}`}const request_id=state.pendingRequestId;button.disabled=true;try{const result=await api('/api/orders',{method:'POST',body:JSON.stringify({request_id,branch,note,items:rows})});state.pendingRequestId=null;state.pendingSignature=null;reset();$("orderNotice").innerHTML=`<div class="save-success">บันทึกคำสั่งซื้อสำเร็จ (Order ID: ${esc(result.order_id)})</div>`}catch(e){$("orderNotice").innerHTML=`<div class="alert">${esc(e.message)}</div>`}finally{button.disabled=false}};


function selectCategory(category){
  currentOrderCategory = category;

  document.querySelectorAll("[data-order-category]").forEach(function(button){
    button.classList.toggle("active", button.dataset.orderCategory === category);
  });

  const products = ORDER_CATALOG[category] || [];
  ORDER_PRODUCTS.splice(0, ORDER_PRODUCTS.length, ...products);

  const title = document.querySelector(".order-layout .card:nth-child(2) h2");
  if (title) title.textContent = "รายการ" + category;

  const search = document.getElementById("orderSearch");
  if (search) {
    search.value = "";
    search.placeholder = "ค้นหารายการ" + category + "...";
  }

  render();
}

document.querySelectorAll("[data-order-category]").forEach(function(button){
  button.addEventListener("click", function(){
    selectCategory(button.dataset.orderCategory);
  });
});

window.authReady.then(async user=>{const catalog=await api('/api/product-catalog');ORDER_CATALOG["หมู"] = catalog.pork || []; ORDER_CATALOG["ไก่"] = catalog.chicken || [];$("orderDate").textContent=new Intl.DateTimeFormat("th-TH",{dateStyle:"long"}).format(new Date());$("orderedBy").textContent=user.username;if(user.role==='manager'){$("orderBranch").value=user.branch;$("orderBranch").disabled=true}selectCategory("หมู"); summary()});
