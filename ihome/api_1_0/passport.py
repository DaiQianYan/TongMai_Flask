# -*- coding:utf-8 -*-

import re

from flask import jsonify, request, current_app, session
from ihome.models import User
from ihome.utils.response_code import RET
from ihome import db, redis_store
from ihome.utils.commons import login_required
from . import api


@api.route("/users", methods=["POST"])
def register():  
    """
    1、获取参数
    2、校验参数
    3、查询数据库
    4、返回结果
    """ 
    #获取json数据，验证参数有效性
    user_data = request.get_json()
    if not user_data:
        return jsonify(errno=RET.PARAMERR, errmsg="参数不完整")
    #进一步校验参数，包括手机号、短信验证码和密码
    mobile = user_data.get("mobile")  
    sms_code = user_data.get("sms_code")  
    password = user_data.get("password") 
    #首先校验参数完整性  
    if not all([mobile, sms_code, password]):
        return jsonify(errno=RET.PARAMERR, errmsg="参数不完整")
    #校验手机号格式，如果不符合要求，直接返回异常信息给前端
    if not re.match(r"^1[34578]\d{9}$", mobile):
        return jsonify(errno=RET.PARAMERR, errmsg="手机号格式不正确")
    #查询数据库，准备校验短信验证码
    try:
        real_sms_code = redis_store.get("SMSCode_" + mobile)
    except Exception as e:
        current_app.logger.error(e)
        return jsonify(errno=RET.DBERR, errmsg="读取验证码异常")
    #如果短信验证码过期，直接返回前端错误信息
    if not real_sms_code:
        return jsonify(errno=RET.DATAERR, errmsg="短信验证码过期")
    #把真实验证码和用户输入的短信验证码进行比对
    if real_sms_code != str(sms_code):
        return jsonify(errno=RET.DATAERR, errmsg="短信验证码无效")
    #如果比对成功，删除缓存中的真实短信验证码
    try:
        redis_store.delete("SMSCode_" + mobile)
    except Exception as e:
        current_app.logger.error(e)
    #获取用户输入密码和手机号信息，准备存入数据库中
    user = User(name=mobile, mobile=mobile)
    user.password = password
    #把用户名和密码存入mysql数据库中
    try:
        db.session.add(user)
        db.session.commit()
    except Exception as e:
        current_app.logger.error(e)
        #如果存入数据发生异常，进行回滚操作
        db.session.rollback()
        return jsonify(errno=RET.DATAEXIST, errmsg="手机号已存在")
    #缓存用户的注册信息
    session["user_id"] = user.id
    session["name"] = mobile
    session["mobile"] = mobile
    return jsonify(errno=RET.OK, errmsg="OK", data=user.to_dict())

@api.route("/sessions", methods=["POST"])
def login():
    """
    1、获取参数
    2、校验参数
    3、查询数据库
    4、返回结果
    """ 
    #获取json参数
    req_data = request.get_json()
    #对参数完整性进行性进行校验
    if not req_data:
        return jsonify(errno=RET.PARAMERR, errmsg="参数不完整")
    #首先校验参数是否完整，包括手机号和密码
    mobile = req_data.get("mobile")
    password = req_data.get("password")    
    if not all([mobile, password]):
        return jsonify(errno=RET.PARAMERR, errmsg="参数不完整")
    #进一步校验具体的每个参数，手机号格式
    if not re.match(r"^1[34578]\d{9}$", mobile):
        return jsonify(errno=RET.PARAMERR, errmsg="手机号格式错误")
    #查询数据库操作，对手机号进行进一步验证
    try:
        user = User.query.filter_by(mobile=mobile).first()
    except Exception as e:
        currnet_app.logger.error(e)
        return jsonify(errno=RET.DBERR,errmsg='查询手机号错误')
    #如果密码或用户名不符合注册信息，直接返回异常信息，但是不要提供真实的异常信息
    if user is None or not user.check_password(password):
        return jsonify(errno=RET.DATAERR, errmsg="手机号或密码错误")
    #把用户登录输入的用户信息缓存到数据库中，并返回前端响应结果
    session["user_id"] = user.id
    session["name"] = user.name
    session["mobile"] = user.mobile
    return jsonify(errno=RET.OK, errmsg="登录成功", data={"user_id": user.id})


@api.route("/session", methods=["GET"])
def check_login():
    """检查登陆状态"""
    # 尝试从session中获取用户的名字
    name = session.get("name")
    # 如果session中数据name名字存在，则表示用户已登录，否则未登录
    if name is not None:
        return jsonify(errno=RET.OK, errmsg="true", data={"name": name})
    else:
        return jsonify(errno=RET.SESSIONERR, errmsg="false")


@api.route("/session", methods=["DELETE"])
@login_required
def logout():
    """登出"""
    # 清除session数据
    session.clear()
    return jsonify(errno=RET.OK, errmsg="OK")
