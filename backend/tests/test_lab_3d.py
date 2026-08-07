def test_lab_fake_end_to_end(client):
 r=client.post('/internal/lab/chat',json={'user_key':'luis','message':'Hola'});assert r.status_code==200 and r.json()['state']=='CHATTING'
 r=client.post('/internal/lab/chat',json={'user_key':'luis','message':'Quiero saber por mi ex'});assert r.json()['state']=='DEFINING_QUESTION'
 r=client.post('/internal/lab/chat',json={'user_key':'luis','message':'Hace dos meses que no hablamos y ayer volvió'});assert r.json()['suggested_spread']=='relationship_three' and r.json()['state']=='READY_FOR_READING'
 r=client.post('/internal/lab/users/luis/reading',json={'question':'¿Qué intención tiene?'});assert r.status_code==200 and r.json()['spread']=='relationship_three' and len(r.json()['cards'])==3 and r.json()['interpretation'] and r.json()['state']=='READING_ACTIVE'
 r=client.post('/internal/lab/chat',json={'user_key':'luis','message':'¿Y qué significa eso para mí?'});assert r.status_code==200
 state=client.get('/internal/lab/users/luis').json();assert state['last_reading_id'] and state['metrics']['calls']>=5
def test_lab_reset_is_scoped_and_invalid_spread(client):
 client.post('/internal/lab/chat',json={'user_key':'a','message':'Hola'});client.post('/internal/lab/chat',json={'user_key':'b','message':'Hola'})
 assert client.post('/internal/lab/users/a/reading',json={'spread_type':'bad'}).status_code==422
 assert client.post('/internal/lab/users/a/reset').json()['reset'] is True
 assert client.get('/internal/lab/users/b').json()['user_id']
