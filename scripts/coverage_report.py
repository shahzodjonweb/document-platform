"""Per-feature accountability. A menu or provider adapter is not release approval."""
import json
import sys
from pathlib import Path
ROOT=Path(__file__).resolve().parent.parent
catalog=json.loads((ROOT/'docs/product/feature_catalog.json').read_text())
backlog=json.loads((ROOT/'docs/product/delivery_backlog.json').read_text())
processors=set('''pdf.merge pdf.compress pdf.split pdf.extract_pages pdf.delete_pages pdf.reorder pdf.rotate pdf.images_to_pdf pdf.to_images pdf.protect pdf.unlock_known convert.word_to_pdf convert.pptx_to_pdf convert.pdf_to_docx convert.pdf_to_xlsx ocr.extract_text ocr.searchable_pdf editor.visual editor.add_text editor.highlight editor.annotate editor.fill_forms editor.signature_image editor.existing_text editor.insert_images editor.replace_images editor.redact editor.export'''.split())
core=set('''capacity.queue pdf.image_layout pdf.compression_preview capacity.file_size capacity.monthly profile.modes profile.locale profile.preferences jobs.progress jobs.history jobs.errors_retry files.no_watermark files.retention usage.balance billing.quote billing.failure_restore support.standard files.previews bot.upload_forward bot.detect_actions'''.split())
commerce=set('''billing.stars billing.subscription billing.task_pack billing.ai_topup billing.trial support.priority growth.referral growth.sponsor growth.ad_free'''.split())
studio=set('''ai.outline template.professional batch.convert batch.compress batch.image_sets workflow.saved workflow.reuse ai.language ai.length_style ai.speaker_notes template.basic template.branding export.generated_pdf export.generated_pptx school.results school.weak_topics school.adult_mode teacher.saved_templates teacher.branding teacher.separate_exports teacher.share_materials editor.form_templates editor.batch_forms'''.split())
partial={'auth.telegram':'Telegram identity/replay/challenge protocols and offline bot behavior tested; real device continuity and live transport need credentials and HTTPS.'}
known=processors|core|commerce|studio|set(partial)
by_feature={}
for ticket in backlog['tickets']:
    for fid in ticket['feature_ids']:
        assert fid not in by_feature,f'Duplicate ticket ownership for {fid}'
        by_feature[fid]=ticket['id']
ids={f['id'] for f in catalog['features']}
assert len(catalog['features'])==128 and len(backlog['tickets'])==48 and set(by_feature)==ids
assert known<=ids
rows=[]
for feature in catalog['features']:
    fid=feature['id']
    if fid in partial:
        status='partial';evidence=['apps/studio','apps/core','telegram','tests'];gate=partial[fid]
    elif fid in processors:
        status='implemented_local';evidence=['processors/engine.py','processors/advanced.py','processors/editor.py','tests/test_advanced_processors.py','tests/test_processors.py','docs/processor-capabilities.md'];gate='Real artifact tests. Supported encodings/layouts and raster-redaction limitations are explicit. Stable Office runtime, parser containment and production quality gates remain.'
    elif fid in core:
        status='implemented_local';evidence=['apps/core','telegram','tests/test_platform.py','tests/test_adversarial.py','tests/test_bot_transport.py','../document-web/docs/design/QA.md'];gate='Local artifact/API/browser behavior verified; live Telegram and production infrastructure qualification remain.'
    elif fid in commerce:
        status='implemented_local';evidence=['apps/commerce','telegram/billing.py','telegram/delivery.py','operations/commerce_views.py','apps/commerce/tests'];gate='Server-priced state machine and sandbox tested. Real Stars provider, reviewed prices/economics and production financial reconciliation need configuration/signoff.'
    elif fid in studio:
        status='implemented_local';evidence=['apps/studio','tests/test_studio.py','tests/test_studio_adversarial.py','tests/test_studio_branding_revisions.py','tests/test_batches.py','tests/test_batch_forms.py'];gate='Local authoring/export, encrypted state and permission tests; provider output quality and multilingual human acceptance remain separate.'
    elif fid.startswith(('ai.','study.','school.','teacher.')):
        status='provider_dependent';evidence=['apps/studio/domain.py','apps/studio/provider.py','apps/studio/execution.py','apps/studio/illustrations.py','apps/studio/packs.py','tests/test_studio_packs.py','tests/test_illustrations.py'];gate='Structured bounded provider adapter and local supplied-content authoring exist. Live credentials/model qualification, task-specific factual/pedagogical evaluation and native-speaker acceptance have not occurred. Images require the live image provider; no fake local generation.'
    else:
        status='gated';evidence=[];gate='No implementation acceptance evidence recorded.'
    rows.append({'id':fid,'name':feature['name'],'release':feature['release'],'ticket':by_feature[fid],'status':status,'production_enabled':False,'evidence':evidence,'gate':gate})
report={'schema_version':'1.1','catalog_count':128,'ticket_count':48,'release_approval':'none','note':'Local capability, adapter presence, and production release are distinct. Original requirements are preserved unchanged.','features':rows}
json_text=json.dumps(report,ensure_ascii=False,indent=2)+'\n'
lines=['# Feature coverage','','All 128 IDs remain assigned to their original owner ticket. No production release is approved.','','- `implemented_local`: implemented behavior with local artifact/API/browser evidence.','- `provider_dependent`: implemented provider/authoring path; live task quality requires configuration and evaluation.','- `partial`: specific remaining behavior or acceptance limitation is recorded in the JSON report.','- `gated`: no implementation acceptance evidence recorded.','','| Feature ID | Ticket | Local status | Production |','|---|---|---|---|']
lines.extend(f"| `{r['id']}` | {r['ticket']} | {r['status']} | disabled |" for r in rows)
lines+=['','Detailed evidence and limitations: [feature-status.json](feature-status.json).','']
target=ROOT/'docs/feature-status.json';markdown='\n'.join(lines)
if '--check' in sys.argv:
    assert target.exists() and target.read_text()==json_text,'Run python scripts/coverage_report.py and review status changes'
    assert (ROOT/'docs/feature-coverage.md').read_text()==markdown,'Coverage markdown is stale'
else:
    target.write_text(json_text);(ROOT/'docs/feature-coverage.md').write_text(markdown)
print(f"Tracked {len(rows)} features / {len(backlog['tickets'])} tickets; {sum(r['status']=='implemented_local' for r in rows)} local implementations, {sum(r['status']=='provider_dependent' for r in rows)} provider-dependent, {sum(r['status']=='partial' for r in rows)} partial; no production gates approved.")
