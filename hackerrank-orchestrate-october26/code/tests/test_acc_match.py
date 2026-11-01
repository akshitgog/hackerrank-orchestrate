import pandas as pd
import json
from code.src.logging_agent.tracker import IdentityTracker
from code.src.audit_agent.scanner import AuditScanner

tracker = IdentityTracker('dataset/user_identities.csv', 'dataset/user_audit_log.csv')
scanner = AuditScanner('dataset/evidence_files.csv', 'dataset/system_activity.csv', 'dataset/deletion_rules.csv', 'cache/multimodal_cache.json')

req_df = pd.read_csv('dataset/sample_deletion_requests.csv')
out_df = pd.read_csv('dataset/sample_output.csv')
act_df = pd.read_csv('dataset/system_activity.csv')

del_acc = act_df[(act_df['source_system'] == 'deletion_worker') & (act_df['target_system'] == 'account_service')].copy()
del_acc['event_dt'] = pd.to_datetime(del_acc['event_time'])

status_map = {'COMPLETE': 'SUCCESS', 'PARTIALLY_COMPLETE': 'PARTIAL', 'NOT_STARTED': 'FAILED'}

correct = 0
for _, r in req_df.iterrows():
    cid = r['case_id']
    prof = tracker.get_identity_profile(r['email'], r['audit_at'])
    gold_steps = json.loads(out_df[out_df['case_id'] == cid]['steps_json'].values[0])
    gold_accs = [s['resource_id'] for s in gold_steps if s['system_id'] == 'account_service']
    gold_acc = gold_accs[0] if gold_accs else None
    
    # 1. From scan
    res = scanner.audit_case(cid, prof, r['audit_at'], requested_at=r.get('requested_at'))
    uid_suffix = prof.user_id.replace('user_', '') if prof else ''
    naive_id = f'account_{uid_suffix}'
    accs_from_scan = [f.resource_id for f in res.findings if f.system_id == 'account_service'] + \
                     [v.resource_id for v in res.verifications if v.system_id == 'account_service' and v.resource_id != naive_id]
    
    pred_acc = None
    if accs_from_scan:
        pred_acc = accs_from_scan[0]
    elif prof and prof.user_id.startswith('user_') and prof.user_id.replace('user_', '').isdigit() and int(prof.user_id.replace('user_', '')) <= 10:
        pred_acc = f"account_{int(prof.user_id.replace('user_', '')):03d}"
    else:
        # system_activity lookup
        rep_at = r['reported_at']
        rep_stat = r['reported_status']
        if pd.notna(rep_at):
            t_req = pd.to_datetime(rep_at)
            sub = del_acc[(del_acc['event_dt'] >= t_req - pd.Timedelta(minutes=90)) & (del_acc['event_dt'] <= t_req + pd.Timedelta(minutes=30))].copy()
            exp_res = status_map.get(rep_stat)
            if exp_res and len(sub[sub['reported_result'] == exp_res]) > 0:
                sub = sub[sub['reported_result'] == exp_res]
            elif rep_stat == 'PARTIALLY_COMPLETE' and len(sub[sub['reported_result'].isin(['PARTIAL', 'SUCCESS'])]) > 0:
                sub = sub[sub['reported_result'].isin(['PARTIAL', 'SUCCESS'])]
            
            if len(sub) > 0:
                sub['diff'] = (sub['event_dt'] - t_req).abs()
                sub = sub.sort_values('diff')
                pred_acc = sub.iloc[0]['resource_id']
                
    match = (pred_acc == gold_acc)
    if match:
        correct += 1
    else:
        print(f"MISMATCH {cid}: gold={gold_acc}, pred={pred_acc}, user={prof.user_id if prof else None}")

print(f"Final matched accounts: {correct}/{len(req_df)}")
