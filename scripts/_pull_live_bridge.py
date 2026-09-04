"""Pull the LIVE bridge.py from the Windows VM for inspection."""
import base64, os
import winrm
from env_loader import load_dotenv
load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), '.env'))

s = winrm.Session(os.environ['HERMES_WIN_IP'],
                  auth=(os.environ['WIN_USER'], os.environ['WIN_PASS']),
                  transport='ntlm', server_cert_validation='ignore',
                  read_timeout_sec=120)
r = s.run_cmd('cmd', ['/c', 'type', 'C:\\Temp\\bridge.py'])
txt = r.std_out.decode('utf-8', 'replace')
open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'logs', 'live_bridge.py'), 'w').write(txt)
print('lines:', len(txt.splitlines()))
import re
for kw in ('/api/', 'ORDER_TYPE', 'TRADE_ACTION'):
    hits = sorted(set(re.findall(r"'[^']*{}[^']*'|\"[^\"]*{}[^\"]*\"".format(re.escape(kw), re.escape(kw)), txt)))
    print(kw, '->', [h for h in hits if 'api' in h or 'ORDER' in h or 'ACTION' in h][:12])
