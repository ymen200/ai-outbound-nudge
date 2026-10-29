import sys 
import builtins 
import mcp_server 
print('BUILTINS_PRINT', builtins.print is mcp_server._original_print, builtins.print, mcp_server._original_print) 
sys.stdout.write('stdout1\n') 
print('print1') 
sys.stderr.write('stderr1\n') 
