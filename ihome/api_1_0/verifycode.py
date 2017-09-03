# -*- coding:utf-8 -*-

import re
import random

from flask import request, jsonify, current_app, make_response
from ihome.utils.response_code import RET
from ihome.utils.captcha.captcha import captcha
from ihome.utils import sms
from ihome import redis_store, constants
from ihome.models import User
from . import api

#生成图片验证码
@api.route("/imagecode/<image_code_id>", methods=["GET"])
def generate_image_code(image_code_id):
    #调用第三方接口来实现图片验证码的获取，name是图片验证码的名字，text图片验证码的内容，image就是图片信息
    name, text, image = captcha.generate_captcha()
    try:
        #把图片验证码存入redis数据库中
        redis_store.setex("ImageCode_" + image_code_id, constants.IMAGE_CODE_REDIS_EXPIRES, text)
    except Exception as e:
        #要把异常信息记录下来，写入日志文件中
        current_app.logger.error(e)
        return jsonify(errno=RET.DBERR, errmsg="保存图片验证码失败")
    else:
        #把图片验证码返回给前端
        response = make_response(image)     
        response.headers["Content-Type"] = "image/jpg"
        return response

#短信验证码
@api.route("/smscode/<mobile>", methods=["GET"])
def send_sms_code(mobile):
    """
    1、判断参数是否存在
    2、判读手机号格式
    3、判断图片验证码--过期--查询--比较
    4、判断手机号是否已注册
    5、生成短信验证码
    """
    #获取请求参数，图片验证码的内容，图片验证码的id
    image_code = request.args.get("text") 
    image_code_id = request.args.get("id") 
    #通过all方法判断参数是否存在
    if not all([mobile, image_code, image_code_id]):
        return jsonify(errno=RET.PARAMERR, errmsg="参数错误")
    #判断手机号格式是否符合要求，通过正则表达式进行判断
    if not re.match(r"^1[34578]\d{9}$", mobile):
        return jsonify(errno=RET.PARAMERR, errmsg="手机号格式错误")
    try:  
        #查询redis数据库中存储的真实图片验证码
        real_image_code = redis_store.get("ImageCode_" + image_code_id)
    except Exception as e:
        current_app.logger.error(e)
        return jsonify(errno=RET.DBERR, errmsg="查询数据异常")
    #图片验证码只能进行一次验证，否则过期重新生成
    if not real_image_code:
        return jsonify(errno=RET.DATAERR, errmsg="图片验证码过期")    
    try:
        #删除redis数据库中存储的图片验证码
        redis_store.delete("ImageCode_" + image_code_id)
    except Exception as e:
        current_app.logger.error(e)    
    #把用户的图片验证码和缓存的真实验证码统一转为一种格式，进行比较
    if image_code.lower() != real_image_code.lower():
        return jsonify(errno=RET.DATAERR, errmsg="图片验证码错误")    
    try:
        #查询手机号是否已经注册
        user = User.query.filter_by(mobile=mobile).first()
    except Exception as e:
        current_app.logger.error(e)
    else:
        if user is not None:
            return jsonify(errno=RET.DBERR, errmsg="手机号已存在")   
    #开始生成短信验证码，格式化输出，确保输出的短信验证码位数
    sms_code = '%06d' % random.randint(0, 1000000)    
    try:
        #把短信验证码存储到redis数据库中
        redis_store.setex("SMSCode_" + mobile, constants.SMS_CODE_REDIS_EXPIRES, sms_code)
    except Exception as e:
        current_app.logger.error(e)
        return jsonify(errno=RET.DBERR, errmsg="保存数据出现错误")    
    try:
        #发送短信验证码
        ccp = sms.CCP()
        result = ccp.send_template_sms(mobile, [sms_code, constants.SMS_CODE_REDIS_EXPIRES/60], 1)
    except Exception as e:
        current_app.logger.error(e)
        return jsonify(errno=RET.THIRDERR, errmsg="发送短信异常")
    #判断语句，建议把变量写在后面，常量建议写在前面，防止表达式错误
    if 0 == result:
        return jsonify(errno=RET.OK, errmsg="发送成功")
    else:
        return jsonify(errno=RET.THIRDERR, errmsg="发送短信失败")
