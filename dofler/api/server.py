from bottle import request, response, Bottle, debug, run, static_file, redirect
from sqlalchemy import (Table, Column, Integer, ForeignKey, PickleType, Text,
                        Sequence, String, DateTime, LargeBinary, and_, desc, 
                        create_engine)
from sqlalchemy.orm import relationship, backref, sessionmaker
from sqlalchemy.ext.declarative import declarative_base
from bottle.ext import sqlalchemy
import datetime
import json
import time
from hashlib import md5
from dofler.log import log
from dofler.config import config

Base = declarative_base()
engine = create_engine(config.get('Settings', 'db_string'))
Session = sessionmaker(engine)
app = Bottle()

app.install(sqlalchemy.Plugin(engine, Base.metadata, create=True))


class Account(Base):
    __tablename__ = 'account'
    id = Column(Integer, Sequence('id_seq'), primary_key=True)
    username = Column(String(128))
    password = Column(String(128))
    info = Column(String(128))
    proto = Column(String(32))
    parser = Column(String(32))

    def __init__(self, username, password, info, proto, parser):
        self.username = username
        self.password = password
        self.info = info
        self.proto = proto
        self.parser = parser


    def __repr__(self):
        return '<Account(%s, %s, %s)>' % (self.id, self.username, self.password)


    def json(self):
        return {
            'id': self.id,
            'username': self.username,
            'password': self.password,
            'info': self.info,
            'proto': self.proto,
            'parser': self.parser,
        }


class Stat(Base):
    __tablename__ = 'stat'
    id = Column(Integer, Sequence('id_seq'), primary_key=True)
    protocol = Column(String(32))
    count = Column(Integer)

    def __init__(self, protocol, count):
        self.protocol = protocol
        self.count = count


    def __repr__(self):
        return '<Stat(%s, %s)>' % (self.protocol, self.count)


    def json(self):
        return {
            'id': self.id,
            'protocol': self.protocol,
            'count': self.count,
        }


class Image(Base):
    __tablename__ = 'image'
    md5 = Column(String(32), primary_key=True)
    lastupload = Column(Integer)
    data = Column(LargeBinary)
    filetype = Column(String(10))

    def __init__(self, data, filetype):
        self.md5 = md5hash(data)
        self.filetype = filetype
        self.lastupload = int(time.mktime(time.gmtime()))
        self.data = data


    def __repr__(self):
        return '<Image(%s)>' % self.md5


    def json(self):
        return {
            'hash': self.md5,
            'timestamp': int(self.lastupload),
        }


def jsonify(dataset):
    return json.dumps(dataset, sort_keys=True, indent=4)


def auth(request):
    sensor = request.get_cookie('account', secret=config.get('Settings', 'key'))
    if sensor: return True
    else: return False


def md5hash(data):
    md5sum = md5()
    md5sum.update(data)
    return md5sum.hexdigest()


def serve():
    debug(config.getboolean('Settings', 'debug'))
    run(app=app,
        port=config.get('Settings', 'port'),
        host=config.get('Settings', 'address'),
        server=config.get('Settings', 'server'),
        reloader=config.getboolean('Settings', 'debug'))


@app.hook('before_request')
def set_json_header():
    response.set_header('Content-Type', 'application/json')
    response.set_header('Access-Control-Allow-Origin', '*')


@app.get('/static/<path:path>')
def static_files(path, db):
    return static_file(path, root='/usr/share/dofler')


@app.get('/')
def home_path(db):
    redirect('/static/viewer.html')


@app.post('/login')
def login(db):
    sensor = request.forms.get('sensor')
    auth = request.forms.get('auth')
    salt = request.forms.get('salt')
    secret = config.get('Sensors', sensor)
    md5sum = md5()
    md5sum.update(sensor)
    md5sum.update(salt)
    md5sum.update(secret)
    if md5sum.hexdigest() == auth:
        response.set_cookie('account', sensor, 
                            secret=config.get('Settings', 'key'),
                            httponly=True)
        return 'Successfully Logged In'
    else:
        return 'Login Failed'


@app.route('/api/accounts/<num:int>')
def recent_accounts(num, db):
    accounts = db.query(Account).filter(Account.id>=num)\
                                .order_by(Account.id).all()
    return jsonify([a.json() for a in accounts])


@app.route('/api/account_total')
def account_total(db):
    return jsonify(db.query(Account).count())


@app.route('/api/images/<num:int>')
def recent_images(num, db):
    images = db.query(Image).filter(Image.lastupload>=num)\
                            .order_by(Image.lastupload).all()
    return jsonify([a.json() for a in images])


@app.route('/api/image/<id>')
def get_image(id, db):
    image = db.query(Image).filter_by(md5=id).first()
    response.set_header('Content-Type', 'image/%s' % image.filetype)
    return image.data


@app.route('/api/stats')
def get_stats(id, db):
    pass


@app.post('/api/post/stats')
def submit_stats(db):
    if auth(request):
        jdata = json.loads(request.forms.get('jdata'))
        for item in jdata:
            db.add(Stat(item, jdata[item]))
            log.debug('SERVER: Adding stat: %s:%s' % (item, jdata[item]))


@app.post('/api/post/account')
def submit_account(db):
    if auth(request):
        username = request.forms.get('username')
        password = request.forms.get('password')
        info = request.forms.get('info')
        proto = request.forms.get('proto')
        parser = request.forms.get('parser')

        try:
            account = db.query(Account).filter_by(username=username,
                                                  password=password,
                                                  info=info,
                                                  proto=proto).first()
        except:
            account = None
        if account == None:
            db.add(Account(username, password, info, proto, parser))
            log.debug('SERVER: Added account %s:%s' % (proto, username))


@app.post('/api/post/image')
def submit_image(db):
    if auth(request):
        filetype = request.forms.get('filetype')
        data = request.files.file
        if data.file:
            raw = data.file.read()
            md5sum = md5hash(raw)
            #print len(raw), md5sum
            try:
                image = db.query(Image).filter_by(md5=md5sum).first()
                image.timestamp = int(time.mktime(time.gmtime()))
                db.merge(image)
                log.debug('SERVER: Updated %s' % image.md5)
            except:
                image = Image(raw, filetype)
                db.add(image)
                log.debug('SERVER: Added %s' % image.md5)