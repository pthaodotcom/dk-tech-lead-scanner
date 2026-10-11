"""Local receiver for sanitized diagnostic summaries; no Facebook access."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import json
import re
from datetime import datetime, timezone

OUT = Path(__file__).resolve().parent.parent / '.local' / 'facebook-test-results'
OUT.mkdir(parents=True, exist_ok=True)

class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def origin(self):
        value = self.headers.get('Origin', '')
        return value if re.fullmatch(r'chrome-extension://[a-p]{32}', value) else None

    def respond(self, status, body=b''):
        self.send_response(status)
        origin = self.origin()
        if origin:
            self.send_header('Access-Control-Allow-Origin', origin)
            self.send_header('Vary', 'Origin')
            self.send_header('Access-Control-Allow-Methods', 'POST, OPTIONS')
            self.send_header('Access-Control-Allow-Headers', 'Content-Type')
            self.send_header('Access-Control-Allow-Private-Network', 'true')
        self.send_header('Content-Type', 'application/json')
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self):
        self.respond(204 if self.origin() else 403)

    def do_GET(self):
        if self.path == '/health':
            self.respond(200, b'{"status":"ready","facebook_access":false}')
        else:
            self.respond(404)

    def do_POST(self):
        if self.path != '/report' or not self.origin():
            self.respond(403)
            return
        try:
            length = int(self.headers.get('Content-Length', '0'))
            if not 0 < length <= 65536:
                raise ValueError('size')
            report = json.loads(self.rfile.read(length))
            allowed = {'status','reason','note','captured','observedGroupQueryNames','reportedAt','action',
                       'expectedPageId','tests','commentTest','kind','name','actingId','at','queryName',
                       'httpStatus','elapsedMs','parsedDocuments','graphQLErrors','itemCount','sample',
                       'hasNextPage','id','hasText','textLength','type','targetUrl','activePageId',
                       'targetPostLoaded','feedbackReady','feedbackSource','alreadyAttempted',
                       'targetPostId','targetGroupId','message','commentId','error','attemptedOnce',
                       'extensionVersion','commentTextVisible','commentIds','probe','version',
                       'detectedBy','compatibility','unknownGroupQueryNames','warnings','code',
                       'detectedKind','expectedKind','occurrences','joinedGroups','groupPosts',
                       'pages','page','newItemCount','newInGroup','totalUniqueGroups','completed',
                       'groupsRequested','groupsProcessed','totalStories','newStories',
                       'returnedPosts','truncatedPosts','historySize','groupResults','groupId',
                       'groupName','storyCount','pageCount','failed','mutationDocSource','mutationReady','duplicateVisible',
                       'expiresInSeconds','availableTabs','url'}
            def validate(value, depth=0):
                if depth > 10:
                    raise ValueError('depth')
                if isinstance(value, dict):
                    if any(k not in allowed for k in value):
                        raise ValueError('unexpected field')
                    for v in value.values(): validate(v,depth+1)
                elif isinstance(value, list):
                    if len(value)>100: raise ValueError('length')
                    for v in value: validate(v,depth+1)
                elif isinstance(value, str) and len(value)>1000:
                    raise ValueError('string length')
            if not isinstance(report, dict): raise ValueError('report')
            validate(report)
            if not isinstance(report.get('status'), str): raise ValueError('missing status')
            report['receivedAt'] = datetime.now(timezone.utc).isoformat()
            filename = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')+'.json'
            (OUT/filename).write_text(json.dumps(report, ensure_ascii=False, indent=2),encoding='utf-8')
            print(json.dumps({'saved':filename,'status':report.get('status'),
                              'tests':[{'kind':t.get('kind'),'status':t.get('status'),'itemCount':t.get('itemCount')} for t in report.get('tests',[])]}),flush=True)
            self.respond(200,b'{"saved":true}')
        except (ValueError,TypeError,KeyError):
            self.respond(400,b'{"saved":false}')

if __name__ == '__main__':
    server = ThreadingHTTPServer(('127.0.0.1',9340),Handler)
    print('READY http://127.0.0.1:9340 - diagnostic reports only',flush=True)
    server.serve_forever()
