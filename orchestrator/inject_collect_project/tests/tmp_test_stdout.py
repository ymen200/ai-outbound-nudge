import sys
from mcp_server import StdoutProxy, _original_print, _original_stdout, _original_stderr
sys.stdout.write('stdout1\n')
print('print1')
sys.stderr.write('stderr1\n')
