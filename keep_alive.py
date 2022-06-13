from flask import Flask, redirect, url_for, request, render_template
from threading import Thread
from replit import db

app = Flask(__name__)


@app.route('/', methods=['POST', 'GET'])
def home():
    if request.method == 'POST':
        user = request.form['channel']
        return redirect(url_for('pomo', channel=user))
    else:
        user = request.args.get('channel')
        if (user):
            return redirect(url_for('pomo', channel=user))
        else:
            return render_template("index.html")


@app.route('/pomoData/<channel>')
def pomoData(channel):
    channel = channel.lower()
    if (channel in list(db.keys())):
        return db.get(channel).value
    return f'Bot instance not running for {channel} please go to the bot twitch channel and type `!join {channel}` with your {channel} account to initiate it.'


@app.route('/pomo/<channel>')
def pomo(channel):
    channel = channel.lower()
    return render_template('pomoBoard.html',
                           title='Pomos on ' + channel,
                           channel=channel)


def run():
    app.run(host='0.0.0.0', port=8080)


def keep_alive():
    t = Thread(target=run)
    t.start()
    