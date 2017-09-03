# -*- coding:utf-8 -*-

from flask import request, jsonify, g, current_app, session
from ihome.utils.response_code import RET
from ihome.models import User
from ihome import db
from ihome.utils.commons import login_required
from ihome.utils.image_storage import storage
from ihome import constants
from . import api


@api.route("/user/name", methods=["PUT"])
@login_required
def change_user_name():
    """
    1、获取参数
    2、校验参数
    3、查询数据库
    4、返回结果
    """ 
    #获取用户信息和具体的json数据
    user_id = g.user_id
    req_data = request.get_json()
    #首先校验参数完整性
    if not req_data:
        return jsonify(errno=RET.PARAMERR, errmsg="参数不完整")
    #进一步对用户名参数进行校验
    name = req_data.get("name")
    if not name:
        return jsonify(errno=RET.PARAMERR, errmsg="名字不能为空")
    #对数据库进行操作，更新用户新输入的用户名信息
    try:
        User.query.filter_by(id=user_id).update({"name": name})
        db.session.commit()
    except Exception as e:
        current_app.logger.error(e)
        #如果更新用户名发生异常，进行回滚操作，并返回前端响应结果
        db.session.rollback()
        return jsonify(errno=RET.DBERR, errmsg="设置用户错误")
    #把用户更新后的数据缓存到数据库中，返回前端响应结果
    session["name"] = name
    return jsonify(errno=RET.OK, errmsg="OK", data={"name": name})


@api.route("/user/avatar", methods=["POST"])
@login_required
def set_user_avatar():
    """
    1、获取参数
    2、校验参数
    3、查询数据库
    4、返回结果
    """ 
    #获取用户信息和参数信息
    user_id = g.user_id
    avatar = request.files.get("avatar")
    #参数不存在
    if not avatar:
        return jsonify(errno=RET.PARAMERR, errmsg="未传头像")
    #把图片信息读取保存
    avatar_data = avatar.read()
    try:
        #调用七牛云接口，实现图片上传
        img_name = storage(avatar_data)
    except Exception as e:
        current_app.logger.error(e)
        return jsonify(errno=RET.THIRDERR, errmsg="上传头像失败")
    try:
        #操作数据库，把用户头像信息的url存储到mysql数据库中
        User.query.filter_by(id=user_id).update({"avatar_url": img_name})
        db.session.commit()
    except Exception as e:
        current_app.logger.error(e)
        db.session.rollback()
        return jsonify(errno=RET.DBERR, errmsg="保存头像失败")
    #拼接图片url信息，并且把响应结果返回给前端
    img_url = constants.QINIU_DOMIN_PREFIX + img_name
    return jsonify(errno=RET.OK, errmsg="保存头像成功", data={"avatar_url": img_url})


@api.route("/user", methods=["GET"])
@login_required
def get_user_profile():
    """
    1、获取参数
    2、校验参数
    3、查询数据库
    4、返回结果
    """ 
    user_id = g.user_id
    try:
        #根据g变量中存储的用户id，查询数据库
        user = User.query.get(user_id)
    except Exception as e:
        current_app.logger.error(e)
        return jsonify(errno=RET.DBERR, errmsg="获取用户信息失败")
    if user is None:
        return jsonify(errno=RET.NODATA, errmsg="无效操作")
    #把用户信息返回给前端，调用了模型类中定义的序列化用户信息的方法to_dict()
    return jsonify(errno=RET.OK, errmsg="OK", data=user.to_dict())


@api.route("/user/auth", methods=["GET"])
@login_required
def get_user_auth():
    """
    1、获取参数
    2、校验参数
    3、查询数据库
    4、返回结果
    """ 
    #获取用户信息
    user_id = g.user_id
    try:
        #根据user_id查询数据库中用户信息
        user = User.query.get(user_id)
    except Exception as e:
        current_app.logger.error(e)
        return jsonify(errno=RET.DBERR, errmsg="获取用户实名信息失败")
    if user is None:
        return jsonify(errno=RET.NODATA, errmsg="无效操作")
    #返回前端正确的响应结果
    return jsonify(errno=RET.OK, errmsg="OK", data=user.auth_to_dict())


@api.route("/user/auth", methods=["POST"])
@login_required
def set_user_auth():  
    """
    1、获取参数
    2、校验参数
    3、查询数据库
    4、返回结果
    """   
    #获取用户信息和参数信息
    user_id = g.user_id
    req_data = request.get_json()
    if not req_data:
        return jsonify(errno=RET.PARAMERR, errmsg="参数错误")
    #接收参数后，对参数进一步校验
    real_name = req_data.get("real_name") 
    id_card = req_data.get("id_card")
    #参数完整性校验
    if not all([real_name, id_card]):
        return jsonify(errno=RET.PARAMERR, errmsg="参数错误")
    try:
        #把用户实名认证信息存入数据库中
        User.query.filter_by(id=user_id, real_name=None, id_card=None)\
            .update({"real_name": real_name, "id_card": id_card})
        db.session.commit()
    except Exception as e:
        #如果存储信息失败，记录日志，并且进行回滚操作
        current_app.logger.error(e)        
        db.session.rollback()
        return jsonify(errno=RET.DBERR, errmsg="保存用户实名信息失败")
    #返回前端保存新成功
    return jsonify(errno=RET.OK, errmsg="OK")
