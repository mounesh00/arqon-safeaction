import assert from 'node:assert/strict';
const base = process.env.WEB_URL || 'http://127.0.0.1:3101';
const call = (path, options) => fetch(base + path, { ...options, signal: AbortSignal.timeout(60000) });
if (process.argv.includes('--unavailable')) {
 const response = await call('/api/v1/health'); assert.equal(response.status,503); assert.equal((await response.json()).error,'BACKEND_UNAVAILABLE'); console.log('PASS backend unavailable');
} else {
 const health = await call('/api/v1/health'); assert.equal(health.status,200); assert.equal((await health.json()).application,'Arqon OS');
 const run = await call('/api/v1/agent/run',{method:'POST',headers:{'Content-Type':'application/json',Origin:base},body:JSON.stringify({task:'Explain what Arqon OS does'})});
 assert.equal(run.status,200); const result=await run.json(); assert.equal(result.status,'completed'); assert.match(result.response,/^MOCK:/);
 const detail=await call('/api/v1/agent/runs/'+result.run_id); assert.equal(detail.status,200); const saved=await detail.json(); assert.equal(saved.run_id,result.run_id); assert.equal(saved.status,'completed'); assert.ok(saved.created_at); assert.equal(saved.response,undefined);
 for (const body of ['{','{"task":""}','{"task":"'+ 'x'.repeat(4001)+'"}','{"task":"ok","provider":"nebius"}']) { const bad=await call('/api/v1/agent/run',{method:'POST',headers:{'Content-Type':'application/json'},body}); assert.equal(bad.status,400); }
 const tooLarge=await call('/api/v1/agent/run',{method:'POST',headers:{'Content-Type':'application/json'},body:'x'.repeat(25000)}); assert.equal(tooLarge.status,413);
 const cross=await call('/api/v1/agent/run',{method:'POST',headers:{'Content-Type':'application/json',Origin:'https://other.example'},body:'{"task":"hello"}'});assert.equal(cross.status,403);
 assert.equal((await call('/api/v1/tools/execute',{method:'POST'})).status,404);
 const html=await (await call('/')).text(); assert.match(html,/Your agent workspace/);
 console.log('PASS health, execution, metadata, 4 invalid inputs, size limit, cross-origin rejection, tool route rejection, page rendering');
}
