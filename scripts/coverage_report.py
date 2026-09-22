"""Full catalog accountability; implementation presence never means release approval."""
import json
import sys
from pathlib import Path
ROOT=Path(__file__).resolve().parent.parent
catalog=json.loads((ROOT/'docs/product/feature_catalog.json').read_text())
backlog=json.loads((ROOT/'docs/product/delivery_backlog.json').read_text())
local_tools={'pdf.merge','pdf.compress','pdf.split','pdf.extract_pages','pdf.delete_pages','pdf.reorder','pdf.rotate','pdf.images_to_pdf','pdf.to_images','pdf.protect','pdf.unlock_known','convert.word_to_pdf','convert.pptx_to_pdf'}
local_support={'pdf.image_layout','pdf.compression_preview','capacity.file_size','capacity.monthly','profile.modes','profile.locale','profile.preferences','jobs.progress','jobs.history','files.no_watermark','files.retention','usage.balance','billing.quote','billing.failure_restore','support.standard','files.previews','bot.upload_forward','bot.detect_actions'}
partial={'auth.telegram','jobs.errors_retry','capacity.queue'}
by_feature={}
for ticket in backlog['tickets']:
 for fid in ticket['feature_ids']:
  assert fid not in by_feature, f'Duplicate ticket ownership for {fid}'
  by_feature[fid]=ticket['id']
assert len(catalog['features'])==128 and len(backlog['tickets'])==48
assert set(by_feature)=={f['id'] for f in catalog['features']}
rows=[]
for feature in catalog['features']:
 fid=feature['id']
 status='implemented_local' if fid in local_tools|local_support else 'partial' if fid in partial else 'gated'
 if fid in local_tools:
  evidence=['processors/engine.py','apps/core/services.py','tests/test_processors.py','tests/test_platform.py','tests/test_adversarial.py']
  gate='Local artifact/API tests; production parser containment and cross-channel real-device gate pending.'
 elif fid in local_support:
  evidence=['apps/core/services.py','apps/core/policy.py','tests/test_platform.py','../document-web/app','../document-web/docs/design/QA.md']
  gate='Local behavior implemented; complete release gate remains pending.'
 elif fid in partial:
  evidence=['apps/core','telegram','tests/test_platform.py','docs/backend-api.md']
  gate='Protocol/domain implementation exists; full transport, preview or fairness acceptance pending.'
 else:
  evidence=[]
  gate={'R1A':'Office engine qualification and actual isolated conversion not yet completed.','R1B':'Depends on R1A release gate, engine qualification, payment configuration, economics and financial integration.','R2A':'Depends on R1B release gate, approved AI provider, structured generation and three-language artifact review.','R2B':'Depends on R2A release gate, education implementation, role-separated artifacts and educator/language review.','R3':'Depends on prior release gates and qualified/licensed existing-content editor and recovery-proof redaction.'}.get(feature['release'],'Foundation acceptance pending.')
 rows.append({'id':fid,'name':feature['name'],'release':feature['release'],'ticket':by_feature[fid],'status':status,'production_enabled':False,'evidence':evidence,'gate':gate})
report={'schema_version':'1.0','catalog_count':128,'ticket_count':48,'release_approval':'none','note':'Local capability is not production release approval. No completion is inferred from a menu or placeholder.','features':rows}
json_text=json.dumps(report,ensure_ascii=False,indent=2)+'\n'
lines=['# Feature coverage','', 'All 128 IDs remain assigned to their original owner ticket. All production releases remain gated.','', '| Feature ID | Ticket | Local status | Production |','|---|---|---|---|']
lines.extend(f"| `{r['id']}` | {r['ticket']} | {r['status']} | disabled |" for r in rows)
lines+=['','Detailed evidence and gates: [feature-status.json](feature-status.json).','']
target=ROOT/'docs/feature-status.json'
if '--check' in sys.argv:
 assert target.exists() and target.read_text()==json_text, 'Run python scripts/coverage_report.py and review the status changes'
else:
 target.write_text(json_text)
 (ROOT/'docs/feature-coverage.md').write_text('\n'.join(lines))
print(f"Tracked {len(rows)} features / {len(backlog['tickets'])} tickets; {sum(r['status']=='implemented_local' for r in rows)} local implementations; no production gates approved.")
