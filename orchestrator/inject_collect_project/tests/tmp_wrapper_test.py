import sys 
class StdoutJsonRoutingWrapper: 
   def __init__(self, stdout, stderr): 
       self._stdout=stdout 
       self._stderr=stderr 
       self._buffer='' 
   def _is_json_line(self,text): 
       import json 
       try: json.loads(text); return True 
       except: return False 
   def _route_line(self,line): 
       if self._is_json_line(line.rstrip('\n')): 
           self._stdout.write(line) 
       else: 
           self._stderr.write(line) 
   def write(self,text): 
       self._buffer += text 
       while '\n' in self._buffer: 
           line, self._buffer = self._buffer.split('\n',1) 
           self._route_line(line+'\n') 
       return len(text) 
   def flush(self): 
       if self._buffer: self._route_line(self._buffer); self._buffer = '' 
       self._stdout.flush(); self._stderr.flush() 
sys.stdout = StdoutJsonRoutingWrapper(sys.stdout, sys.stderr) 
sys.stdout.write('stdout1\n') 
print('print1') 
sys.stderr.write('stderr1\n') 
