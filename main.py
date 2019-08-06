from flask import Flask, g, render_template, make_response, request, redirect, url_for, jsonify
from flask_socketio import SocketIO, send, emit
from threading import Thread
import rethinkdb
import json
import time
from datetime import datetime

from pprint import pprint

app = Flask(__name__)
socketio = SocketIO(app)
global thread
thread = None

r = rethinkdb.RethinkDB()

# Load default config and override config from an environment variable
app.config.update(dict(
    DEBUG=True,
    SECRET_KEY='secret!',
    DB_HOST='db',
    DB_PORT=28015,
    DB_NAME='chat'
))
app.config.from_envvar('FLASKR_SETTINGS', silent=True)

def init_db():
    conn = r.connect(app.config['DB_HOST'], app.config['DB_PORT'])
    try:
        r.db_create(app.config['DB_NAME']).run(conn)
        r.db(app.config['DB_NAME']).table_create('chats').run(conn)
        r.db(app.config['DB_NAME']).table_create('games').run(conn)
        r.db(app.config['DB_NAME']).table('chats').index_create('created').run(conn)
        print('Database setup completed.')
    except:
        print('App database already exists.')
    finally:
        conn.close()

@app.before_request
def before_request():
    g.db_conn = r.connect(
        host=app.config['DB_HOST'], 
        port=app.config['DB_PORT'], 
        db=app.config['DB_NAME'])

@app.teardown_request
def teardown_request(exception):
    try:
        g.db_conn.close()
    except AttributeError:
        pass

@app.route('/chats/', methods=['POST'])
def create_chat():
    data = json.loads(request.data)
    data['created'] = datetime.now(r.make_timezone('00:00'))
    if data.get('name') and data.get('message'):
        r.table("chats").insert([ data ]).run(g.db_conn)
        return make_response('success!', 201)
    return make_response('invalid chat', 401)


@app.route('/', methods=['GET']) 
def list_shows():
    chats = list(r.table("chats").order_by(index=r.desc('created')).limit(20).run(g.db_conn))
    games = list(r.table('games').limit(1).run(g.db_conn))
    game = games[0]
    return render_template('chats.html', chats=chats, game=game)

@app.route('/game/', methods=['GET'])
def get_game():
    games = list(r.table('games').limit(1).run(g.db_conn))
    game = games[0]
    pprint(game)
    return make_response(jsonify(game), 200)

@app.route('/move/', methods=['POST'])
def move():
    start_time = time.time()
    # FIXME: Validate that the move sent is actually legitimate
    data = json.loads(request.data)
    selected_field = int(data['tile'])
    games = r.table('games').limit(1).run(g.db_conn)
    for game in games:
        game['field'][int(selected_field / 17)][selected_field % 17] = game['player_to_move']
        game['player_to_move'] = (game['player_to_move'] + 1)

        # This modulus seems a little verbose, but it is needed to get 1..n instead of 0..n-1
        if game['player_to_move'] > game['players']:
            game['player_to_move'] = game['player_to_move'] % game['players']

        print('New player to move is {}'.format(game['player_to_move']))
        r.table('games').get(game['id']).update(
            {
                'field': game['field'],
                'player_to_move': game['player_to_move']
            }).run(g.db_conn)
            
    print('Time to process POST: {}'.format(time.time() - start_time))
    return make_response('', 200)

@app.route('/reset/', methods=['POST'])
def reset():
    r.table('games').limit(1).update({
        'field': [
            [0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0],
            [0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0],
            [0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0],
            [0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0],
            [0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0],
            [0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0],
            [0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0],
            [0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0],
            [0,0,0,0,0,0,0,0,-1,0,0,0,0,0,0,0,0],
            [0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0],
            [0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0],
            [0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0],
            [0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0],
            [0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0],
            [0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0],
            [0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0],
            [0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0]
        ],
        'players': 4,
        'player_to_move': 1,
    }).run(g.db_conn)
    return make_response('', 200)

def watch_game():
    conn = r.connect(host=app.config['DB_HOST'], 
                     port=app.config['DB_PORT'], 
                     db=app.config['DB_NAME'])
    try:
        feed = r.table("games").changes().run(conn)
        for game in feed:
            socketio.emit('refresh_field', game)
        print('Watching for field changes.')
    except rethinkdb.errors.ReqlOpFailedError:
        print('Could not watch for field changes.')

def watch_chats():
    print('Watching db for new chats!')
    conn = r.connect(host=app.config['DB_HOST'], 
                     port=app.config['DB_PORT'], 
                     db=app.config['DB_NAME'])
    try:
        feed = r.table("chats").changes().run(conn)
        for chat in feed:
            if chat['new_val'] != None:
                chat['new_val']['created'] = str(chat['new_val']['created'])
                if (chat['old_val'] != None):
                    # A chat has been updated
                    chat['old_val']['created'] = str(chat['old_val']['created'])
                    print('Going to update')
                    socketio.emit('update_chat', chat)
                else:
                    # A new chat has been received
                    socketio.emit('new_chat', chat)
            else:
                # A chat has been removed
                chat['old_val']['created'] = str(chat['old_val']['created'])
                socketio.emit('delete_chat', chat)
                print('Emitted signal to delete a chat')
    except rethinkdb.errors.ReqlOpFailedError:
        print("Could not poll for changes in chat")

if __name__ == "__main__":
    init_db()
    time.sleep(1)
    # Set up rethinkdb changefeeds before starting server
    if thread is None:
        thread = Thread(target=watch_game)
        thread.start()
        # thread = Thread(target=watch_chats)
        # thread.start()
    socketio.run(app, host='0.0.0.0', port=8000)



