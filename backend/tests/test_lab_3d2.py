from sqlalchemy import select
from app.models.ai import AICall
from app.models.user import User
def test_state_contract_metrics_and_no_debug(client):
 assert client.get('/internal/lab/users/missing').status_code==404
 client.post('/internal/lab/chat',json={'user_key':'metrics','message':'Hola'})
 data=client.get('/internal/lab/users/metrics').json();m=data['metrics']
 assert data['user_key']=='metrics' and {'total_ai_calls','successful_ai_calls','failed_ai_calls','calls_with_known_cost','calls_with_unknown_cost'}<=m.keys() and 'debug_payload' not in str(data)
 assert m['total_ai_calls']==1 and m['successful_ai_calls']==1
def test_refresh_and_reset_scope(client):
 for key in ('a','b'):
  client.post('/internal/lab/chat',json={'user_key':key,'message':'Hola'})
  client.post('/internal/lab/chat',json={'user_key':key,'message':'Quiero saber por mi ex'})
  client.post('/internal/lab/chat',json={'user_key':key,'message':'Hace dos meses que no hablamos'})
 refresh=client.post('/internal/lab/users/a/memory/refresh').json();assert {'updated','version','summary','reason'}<=refresh.keys()
 assert client.post('/internal/lab/users/a/reset').json()['reset'] is True
 assert client.get('/internal/lab/users/a').status_code==404
 b=client.get('/internal/lab/users/b').json();assert b['suggested_spread']=='relationship_three'
 assert client.post('/internal/lab/users/a/reading',json={}).status_code==422
