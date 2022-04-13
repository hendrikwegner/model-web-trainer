import time
import os
import glob
import json
import requests
import paho.mqtt.client as mqttClient
from flask import Flask, render_template, request,  jsonify, redirect, url_for


app = Flask(__name__)
app.config['TEMPLATES_AUTO_RELOAD'] = True

from tinydb import TinyDB, Query, where
db = TinyDB('/root/db.json')
db_images = db.table('images')

os.chdir("/root")

def getEnv(key, defaultValue):
    value = os.getenv(key)
    if value is None or (len(value) == 0):
        return defaultValue
    return value


frigate_endpoint = getEnv("FRIGATE_ENDPOINT", '192.168.123.4:5000')
mqtt_endpoint_host = getEnv("MQTT_ENDPOINT_HOST", '192.168.123.4')
mqtt_endpoint_port = int(getEnv("MQTT_ENDPOINT_PORT", 1883))
mqtt_user = getEnv("MQTT_USER", 'hendrik')
mqtt_password = getEnv("MQTT_PASSWORD", 'hendrikmqtt')


#mqtt connect
def on_connect(client, userdata, flags, rc):
    if rc == 0:
        print("Connected to broker")
        global Connected                #Use global variable
        Connected = True                #Signal connection
    else:
        print("Connection failed")

#mqtt message recieved
def on_message(client, userdata, message):
    os.chdir("/root")
    data = json.loads(message.payload.decode())
    if data['before']['label'] == "car":
        return
    url = "http://"+frigate_endpoint+"/api/events/" + data['before']['id'] + "/thumbnail.jpg"
    r = requests.get(url, allow_redirects=True)
    new_image = './static/images/'+data['before']['id']+'-'+ str(round(time.time(),2)).replace(".","-") +'.jpg'
    os.makedirs(os.path.dirname(new_image), exist_ok=True)
    #image = './static/'+data['before']['id']+'.jpg'
    open(new_image, 'wb').write(r.content)




    unique = True



    for file in glob.glob("./static/images/"+data['before']['id']+"*"):
        if file in new_image:
            continue
        if open(file,"rb").read() == open(new_image,"rb").read():
            unique = False
            #print("would remove file: " + file + " same as: " + new_image)
           #os.remove(file)
            #db_images.remove(where('url') == "http://192.168.123.4:8070/static/images/"+file)


    if unique:
        db_images.insert({'label': data['before']['label'], 'url': "http://192.168.123.4:8070"+new_image[1:], "eventid": data['before']['id'], "camera": data['before']['camera']})


Connected = False   #global variable for the state of the connection
client = mqttClient.Client("classification-watcher")               #create new instance
client.username_pw_set(mqtt_user, password=mqtt_password)    #set username and password
client.on_connect= on_connect                      #attach function to callback
client.on_message= on_message                      #attach function to callback
client.connect(mqtt_endpoint_host, port=mqtt_endpoint_port)          #connect to broker
client.loop_start()        #start the loop

while Connected != True:    #Wait for connection
    time.sleep(0.1)

client.subscribe("frigate/events")

cameras = ['Pond', 'Street', "Backgarden", "Backside"]
labels = ["bird"]

@app.route('/', methods = ['POST', 'GET'])
def index():
    images = db_images.search((where('label').one_of(labels) & (where('camera').one_of(cameras))))
    return render_template('index.html', time=time.time(), data=images, req=request.url, labels=labels, cameras=cameras)

@app.route('/updateSettings', methods = ['POST'])
def updateSettings():
    global cameras
    global labels
    cameras = json.loads(request.data).get('cameras')
    labels = json.loads(request.data).get('labels')

    return redirect(url_for('index'))



@app.route('/save', methods = ['POST'])
def save():
    model = json.loads(request.data).get('model')
    name = json.loads(request.data).get('name')
    r = requests.get('http://192.168.123.4:8083/classificationbox/state/'+model)
    os.makedirs('./static/models/', exist_ok=True)
    if name == None:
        open('./static/models/'+model+'.classificationbox', 'wb').write(r.content)
    else:
        open('./static/models/'+model+'-'+name+'.classificationbox', 'wb').write(r.content)

    return {"success": model+" saved as: "+str(name)}

@app.route('/load', methods = ['POST'])
def load():
    model = json.loads(request.data).get('model')
    r = requests.post('http://192.168.123.4:8083/classificationbox/state', json={"url": "http://192.168.123.4:8070/static/models/"+model})
    return r.json()


@app.route('/models')
def models():
    return jsonify(glob.glob('./static/models/*'))


@app.route('/modelInfo', methods = ['POST'])
def modelInfo():
    model = json.loads(request.data).get('model')
    r = requests.get('http://192.168.123.4:8083/classificationbox/models/'+model)
    return r.json()

@app.route('/stats', methods = ['POST'])
def stats():
    model = json.loads(request.data).get('model')
    r = requests.get('http://192.168.123.4:8083/classificationbox/models/'+model+'/stats')
    return r.json()

@app.route('/loadedModels')
def loadedModels():
    r = requests.get('http://192.168.123.4:8083/classificationbox/models')
    return r.json()

@app.route('/createModel', methods = ['POST'])
def createModel():
    try:
        r = requests.post('http://192.168.123.4:8083/classificationbox/models', json={
                    "id": json.loads(request.data).get('id'),
                    "name": json.loads(request.data).get('name'),
                    "options": json.loads(request.data).get('options'),
                    "classes": json.loads(request.data).get('classes')
                })
        return r.json()
    except requests.exceptions.JSONDecodeError as e:
        return {"success":str(e)}



@app.route('/removeLoadedModel', methods = ['POST'])
def removeLoadedModel():
    model = json.loads(request.data).get('model')
    r = requests.delete('http://192.168.123.4:8083/classificationbox/models/'+model)
    return r.json()



@app.route('/remove', methods = ['POST'])
def remove():
    url = json.loads(request.data).get('url')
    db_images.remove(Query().url == url)
    return {'removed': True}


@app.route('/train', methods = ['POST'])
def train():

    url = json.loads(request.data).get('url')
    label = json.loads(request.data).get('label')
    model = json.loads(request.data).get('model')

    if label == "remove":
        db_images.remove(Query().url == url)
        return {}

    r = requests.get(url, allow_redirects=True)
    image = './static/training/'+label+'/'+str(time.time())+'.jpg'
    os.makedirs(os.path.dirname(image), exist_ok=True)
    open(image, 'wb').write(r.content)

    r = requests.post('http://192.168.123.4:8083/classificationbox/models/'+model+'/teach', json={
            "class": label,
            "inputs": [
                {
                    "key": "object",
                    "type": "image_url",
                    "value": url
                }
            ]
        })

    db_images.remove(Query().url == url)
    return r.json()


@app.route('/trainUpload', methods = ['POST'])
def trainUpload():

    label = json.loads(request.data).get('label')
    b64_img = json.loads(request.data).get('b64_img')
    model = json.loads(request.data).get('model')

    r = requests.post('http://192.168.123.4:8083/classificationbox/models/'+model+'/teach', json={
            "class": label,
            "inputs": [
                {
                    "key": "object",
                    "type": "image_base64",
                    "value": b64_img
                }
            ]
        })

    return r.json()

@app.route('/massTrainUpload', methods = ['POST'])
def massTrainUpload():

    model = json.loads(request.data).get('model')
    body = json.loads(request.data).get('body')

    r = requests.post('http://192.168.123.4:8083/classificationbox/models/'+model+'/teach-multi', json=body)

    return r.json()


@app.route('/predict', methods = ['POST'])
def predict():
    if json.loads(request.data).get('url'):
        url = json.loads(request.data).get('url')
        model = json.loads(request.data).get('model')

        r = requests.post('http://192.168.123.4:8083/classificationbox/models/'+ model +'/predict', json={
                "inputs": [
                    {
                        "key": "object",
                        "type": "image_url",
                        "value": url
                    }
                ]
            })
        return r.json()




@app.route('/predict_upload', methods = ['POST'])
def predict_upload():

    model = json.loads(request.data).get('model')
    b64_img = json.loads(request.data).get('b64_img')

    r = requests.post('http://192.168.123.4:8083/classificationbox/models/'+model+'/predict', json={
                "inputs": [
                    {
                        "key": "object",
                        "type": "image_base64 ",
                        "value": b64_img
                    }
                ]
            })

    print(r.json())

    return r.json()


@app.route('/getFrigateImages', methods = ['POST'])
def getFrigateImages():

    frigate_camera = json.loads(request.data).get('camera')
    frigate_label = json.loads(request.data).get('label')


    r = requests.get('http://192.168.123.4:5000/api/events?limit=10000&label='+frigate_label+'&include_thumbnails=1&camera='+frigate_camera)

    return {"data": r.json()}




try:
    app.run(debug = False, host = '0.0.0.0', port = 8070, use_reloader = False)
    while True:
        time.sleep(1)

except KeyboardInterrupt:
    print("exiting")
    client.disconnect()
    client.loop_stop()



@app.route('/predict_upload', methods = ['POST'])
def predict_upload():

    model = json.loads(request.data).get('model')
    b64_img = json.loads(request.data).get('b64_img')

    r = requests.post('http://192.168.123.4:8083/classificationbox/models/'+model+'/predict', json={
                "inputs": [
                    {
                        "key": "object",
                        "type": "image_base64 ",
                        "value": b64_img
                    }
                ]})
    return r.json()
