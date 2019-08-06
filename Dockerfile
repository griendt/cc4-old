FROM python:3.7

# ENV PYTHONUNBUFFERED 1
# ENV LK_ENV development_docker
# ENV TERM linux

RUN mkdir /code

RUN pip install flask
RUN pip install flask_socketio
RUN pip install rethinkdb

WORKDIR /code

ADD . /code/