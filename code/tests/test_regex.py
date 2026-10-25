import re

line1 = '{"trace_id":"tr-9028396","resource_id":"audit_record_4902"}'
line2 = 'trace_id=tr-9028396 resource_id=audit_record_4902'

pat_t = r'["\']?(?:trace_id|requestId)["\']?[:=]\s*["\']?([^"\'\s,]+)'
pat_r = r'["\']?resource_id["\']?[:=]\s*["\']?([^"\'\s,]+)'

print('line1:', re.search(pat_t, line1).group(1), re.search(pat_r, line1).group(1))
print('line2:', re.search(pat_t, line2).group(1), re.search(pat_r, line2).group(1))
