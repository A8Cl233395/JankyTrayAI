from individual_modules import *

def _run_server(main_model, vision_model, assist_model):
    app = Flask(__name__)
    CORS(app)
    chatinstances: dict[int, ChatInstance] = {}
    timeouts: dict[int, int] = {}
    conn = sqlite3.connect('saves/history_titles.db', check_same_thread=False, timeout=5)
    with conn:
        cursor = conn.cursor()
        cursor.execute("PRAGMA busy_timeout = 5000")
        cursor.execute("PRAGMA cache_size = -64000")
    
    @app.before_request
    def handle_options():
        if request.method == 'OPTIONS':
            response = jsonify()
            response.headers.add('Access-Control-Allow-Origin', 'http://127.0.0.1:3417')
            response.headers.add('Access-Control-Allow-Headers', 'Content-Type')
            response.headers.add('Access-Control-Allow-Methods', 'GET,POST,OPTIONS')
            response.headers.add('Access-Control-Max-Age', '86400')  # 缓存24小时
            return response

    @app.route('/')
    def index():
        return send_from_directory('assets', 'index.html')
    
    @app.route('/script.js')
    def script():
        return send_from_directory('assets', 'script.js')
    
    @app.route('/style.css')
    def style():
        return send_from_directory('assets', 'style.css')
    
    @app.route('/favicon.ico')
    def favicon():
        return send_from_directory('assets', 'favicon.ico')
    
    @app.route('/get')
    def get():
        args = request.args
        if 'id' in args:
            id = int(args['id'])
            if id in chatinstances:
                return jsonify(chatinstances[id].messages)
            else:
                response = make_response(send_from_directory(f'saves/histories/{id // 1000}', str(id % 1000)))
                response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
                response.headers['Pragma'] = 'no-cache'
                return response
        elif 'below' in args:
            id = int(args['below'])
            with conn:
                cursor = conn.cursor()
                cursor.execute("SELECT id, title FROM titles WHERE id < ? ORDER BY id DESC LIMIT 20", (int(id),))
                titles = [{'id': row[0], 'title': row[1]} for row in cursor.fetchall()]
            return jsonify(titles)
        elif 'above' in args:
            id = int(args['above'])
            with conn:
                cursor = conn.cursor()
                cursor.execute("SELECT id, title FROM titles WHERE id > ? ORDER BY id ASC LIMIT 20", (int(id),))
                titles = [{'id': row[0], 'title': row[1]} for row in cursor.fetchall()]
            return jsonify(titles)
        else:
            with conn:
                cursor = conn.cursor()
                cursor.execute("SELECT id, title FROM titles ORDER BY id DESC LIMIT 20")
                titles = [{'id': row[0], 'title': row[1]} for row in cursor.fetchall()]
            return jsonify(titles)
    
    def _generate_title_and_insert_and_return(queue: Queue, user_input: str, chat_id: int):
        title = ask_ai(system="你是一个专业的标题生成器", user=user_input[-1]["text"] if len(user_input) < 40 else user_input[-1]["text"][:20] + "\n...\n" + user_input[-1]["text"][-20:], model=assist_model, prefix="```标题\n", stop="\n```")
        with conn:
            cursor = conn.cursor()
            cursor.execute("UPDATE titles SET title = ? WHERE id = ?", (title, chat_id))
        queue.put({"title": title})
    
    def _generate_and_insert(queue: Queue, user_inputs: str, chat_id: int, title_thread: threading.Thread = None):
        if chat_id not in chatinstances:
            chatinstances[chat_id] = ChatInstance(model=main_model, vision_model=vision_model)
        chatinstance = chatinstances[chat_id]
        chatinstance.new()
        chatinstance.set(user_inputs)
        for data in chatinstance():
            queue.put(data)
        if title_thread and title_thread.is_alive():
            title_thread.join()
        queue.put(None)
    
    def _generater(queue: Queue):
        is_first = True
        while True:
            message = queue.get()
            if message == None:
                break
            if is_first:
                yield f"data: {json.dumps(message, ensure_ascii=False)}"
                is_first = False
                continue
            yield f"\n\ndata: {json.dumps(message, ensure_ascii=False)}"
    
    def _timeout_checker(id):
        timeouts[id] = time.time()
        while True:
            if time.time() - timeouts[id] > 15:
                print(f"Timeout {id}")
                if id not in chatinstances:
                    return
                folder = id // 1000
                if not os.path.exists(f'saves/histories/{folder}'):
                    os.makedirs(f'saves/histories/{folder}')
                with open(f'saves/histories/{folder}/{id % 1000}', 'w', encoding='utf-8') as f:
                    json.dump(chatinstances[id].messages, f, ensure_ascii=False)
                del chatinstances[id]
                del timeouts[id]
                break
            time.sleep(10)

    @app.route('/generate', methods=['POST'])
    def generate():
        request_body = request.get_json()
        message_queue = Queue()
        if "id" not in request_body:
            with conn:
                cursor = conn.cursor()
                cursor.execute("INSERT INTO titles (title) VALUES (?)", ("新对话",))
                id = cursor.lastrowid
            message_queue.put({"id": id})
            title_thread = threading.Thread(target=_generate_title_and_insert_and_return, args=(message_queue, request_body["content"], id))
            title_thread.start()
            threading.Thread(target=_generate_and_insert, args=(message_queue, request_body["content"], id, title_thread)).start()
            if id not in timeouts:
                threading.Thread(target=_timeout_checker, args=(id,)).start()
            return Response(_generater(message_queue), mimetype='text/event-stream')
        else:
            id = int(request_body["id"])
            if id not in chatinstances:
                with open(f'saves/histories/{id // 1000}/{id % 1000}', 'r', encoding='utf-8') as f:
                    chatinstances[id] = ChatInstance(model=main_model, vision_model=vision_model, messages=json.load(f))
            threading.Thread(target=_generate_and_insert, args=(message_queue, request_body["content"], id)).start()
            if id not in timeouts:
                threading.Thread(target=_timeout_checker, args=(id,)).start()
            return Response(_generater(message_queue), mimetype='text/event-stream')
    
    @app.route('/save', methods=['GET', 'POST'])
    def save():
        args = request.args
        id = int(args['id'])
        if id not in chatinstances:
            return 'ok'
        folder = id // 1000
        if not os.path.exists(f'saves/histories/{folder}'):
            os.makedirs(f'saves/histories/{folder}')
        with open(f'saves/histories/{folder}/{id % 1000}', 'w', encoding='utf-8') as f:
            json.dump(chatinstances[id].messages, f, ensure_ascii=False)
        del chatinstances[id]
        return 'ok'
    
    @app.route('/configure', methods=['POST'])
    def configure():
        global main_model, vision_model, assist_model
        request_body = request.get_json()
        print(request_body)
        if "main_model" in request_body:
            main_model = request_body["main_model"]
        if "vision_model" in request_body:
            vision_model = request_body["vision_model"]
        if "assist_model" in request_body:
            assist_model = request_body["assist_model"]
        return 'ok'
    
    @app.route('/alive')
    def alive():
        args = request.args
        id = int(args['id'])
        if id not in timeouts:
            return 'ok'
        timeouts[id] = time.time()
        return 'ok'

    @app.route('/archive-all')
    def archive_all():
        for i in chatinstances:
            folder = i // 1000
            if not os.path.exists(f'saves/histories/{folder}'):
                os.makedirs(f'saves/histories/{folder}')
            with open(f'saves/histories/{folder}/{i % 1000}', 'w', encoding='utf-8') as f:
                json.dump(chatinstances[i].messages, f, ensure_ascii=False)
        return 'ok'

    app.run(debug=False, host='127.0.0.1', port=3417)

if __name__ == '__main__':
    _run_server("deepseek-chat", "qwen3-vl-plus-2025-12-19", "deepseek-chat")