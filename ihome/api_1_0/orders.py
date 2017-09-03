# -*- coding:utf-8 -*-

import datetime

from flask import request, g, jsonify, current_app
from ihome import db, redis_store
from ihome.utils.commons import login_required
from ihome.utils.response_code import RET
from ihome.models import House, Order
from . import api


@api.route("/orders", methods=["POST"])
@login_required
def save_order():
    """保存订单"""
    #获取用户id
    user_id = g.user_id
    #尝试获取参数
    order_data = request.get_json()
    #参数是否存在
    if not order_data:
        return jsonify(errno=RET.PARAMERR, errmsg="参数错误")
    #进一步获取参数信息，房屋id、开始日期、结束日期
    house_id = order_data.get("house_id")  
    start_date_str = order_data.get("start_date")  
    end_date_str = order_data.get("end_date") 
    #对参数完整性进行校验 
    if not all([house_id, start_date_str, end_date_str]):
        return jsonify(errno=RET.PARAMERR, errmsg="参数错误")
    #格式化日期，断言开始日期小于结束日期，
    try:
        start_date = datetime.datetime.strptime(start_date_str, "%Y-%m-%d")
        end_date = datetime.datetime.strptime(end_date_str, "%Y-%m-%d")
        assert start_date <= end_date
        #计算入住天数
        days = (end_date - start_date).days + 1
    except Exception as e:
        current_app.logger.error(e)
        return jsonify(errno=RET.PARAMERR, errmsg="日期格式错误")
    #获取房屋id
    try:
        house = House.query.get(house_id)
    except Exception as e:
        current_app.logger.error(e)
        return jsonify(errno=RET.DBERR, errmsg="获取房屋信息失败")
    #进一步校验查询结果，房屋不存在
    if not house:
        return jsonify(errno=RET.NODATA, errmsg="房屋不存在")
    #确保房东不能预订自己的房屋
    if user_id == house.user_id:
        return jsonify(errno=RET.ROLEERR, errmsg="不能预订自己的房屋")
    #确保用户选择的房屋未被预订，日期没有冲突
    try:
        count = Order.query.filter(Order.house_id == house_id, Order.begin_date <= end_date,
                                   Order.end_date >= start_date).count()
    except Exception as e:
        current_app.logger.error(e)
        return jsonify(errno=RET.DBERR, errmsg="检查出错，请稍候重试")
    #校验查询结果
    if count > 0:
        return jsonify(errno=RET.DATAERR, errmsg="房屋已被预订")
    #生成订单信息，计算总价，保存订单信息到数据库中
    amount = days * house.price
    order = Order()
    order.house_id = house_id
    order.user_id = user_id
    order.begin_date = start_date
    order.end_date = end_date
    order.days = days
    order.house_price = house.price
    order.amount = amount
    #把订单数据存储到mysql数据库中，如果发生异常，进行回滚操作
    try:
        db.session.add(order)
        db.session.commit()
    except Exception as e:
        current_app.logger.error(e)
        db.session.rollback()
        return jsonify(errno=RET.DBERR, errmsg="保存订单失败")
    #返回响应数据
    return jsonify(errno=RET.OK, errmsg="OK", data={"order_id": order.id})


@api.route("/user/orders", methods=["GET"])
@login_required
def get_user_orders():
    """获取订单信息"""
    #获取用户id
    user_id = g.user_id
    #获取用户角色参数
    role = request.args.get("role", "")
    #验证用户角色
    try:
        #如果角色为房东，首先查询该房东共有多少房子，然后查询订房信息
        if "landlord" == role:
            houses = House.query.filter(House.user_id == user_id).all()
            houses_ids = [house.id for house in houses]
            orders = Order.query.filter(Order.house_id.in_(houses_ids)).order_by(Order.create_time.desc()).all()
        #如果角色为普通订房者
        else:
            orders = Order.query.filter(Order.user_id == user_id).order_by(Order.create_time.desc()).all()
    except Exception as e:
        current_app.logger.error(e)
        return jsonify(errno=RET.DBERR, errmsg="查询订单信息失败")
    #构造响应数据，返回前端
    orders_dict_list = []
    if orders:
        for order in orders:
            orders_dict_list.append(order.to_dict())
    #返回前端响应数据
    return jsonify(errno=RET.OK, errmsg="OK", data={"orders": orders_dict_list})


@api.route("/orders/<int:order_id>/status", methods=["PUT"])
@login_required
def accept_reject_order(order_id):
    """接单拒单操作"""
    #首先获取用户id
    user_id = g.user_id
    #获取参数
    req_data = request.get_json()
    #校验参数是否存在
    if not req_data:
        return jsonify(errno=RET.PARAMERR, errmsg="参数错误")
    #尝试获取参数，前端发送过来的具体接单或拒单的操作
    action = req_data.get("action")
    #校验参数
    if action not in ("accept", "reject"):
        return jsonify(errno=RET.PARAMERR, errmsg="参数错误")
    #查询数据库，验证订单信息，以及订单状态为待接单状态
    try:
        order = Order.query.filter(Order.id == order_id, Order.status == "WAIT_ACCEPT").first()
        house = order.house
    except Exception as e:
        current_app.logger.error(e)
        return jsonify(errno=RET.DBERR, errmsg="无法获取订单数据")
    #确保房东操作的是自己房屋
    if not order or house.user_id != user_id:
        return jsonify(errno=RET.REQERR, errmsg="操作无效")
    #如果是接单操作，直接修改订单状态为待评价
    if action == "accept":
        order.status = "WAIT_COMMENT"
    #如果为拒单
    elif action == "reject":
        #尝试获取拒单原因
        reason = req_data.get("reason")
        if not reason:
            return jsonify(errno=RET.PARAMERR, errmsg="参数错误")
        #修改订单状态为已拒单，并把拒单原因保存起来
        order.status = "REJECTED"
        order.comment = reason
    #把订单操作写入数据库，如果发生异常，进行回滚操作
    try:
        db.session.add(order)
        db.session.commit()
    except Exception as e:
        current_app.logger.error(e)
        db.session.rollback()
        return jsonify(errno=RET.DBERR, errmsg="操作失败")
    #返回前端响应数据
    return jsonify(errno=RET.OK, errmsg="OK")


@api.route("/orders/<int:order_id>/comment", methods=["PUT"])
@login_required
def save_order_comment(order_id):
    """保存订单评价信息"""
    #获取用户id
    user_id = g.user_id
    #获取参数
    req_data = request.get_json()
    #进一步获取用户输入的评价内容
    comment = req_data.get("comment")  
    #如果参数不存在，直接返回结果
    if not comment:
        return jsonify(errno=RET.PARAMERR, errmsg="参数错误")
    #查询数据库，订单必须存在、用户和订房用户必须是同一人、订单状态必须为待评价
    try:
        order = Order.query.filter(Order.id == order_id, Order.user_id == user_id,
                                   Order.status == "WAIT_COMMENT").first()
        house = order.house
    except Exception as e:
        current_app.logger.error(e)
        return jsonify(errno=RET.DBERR, errmsg="无法获取订单数据")
    #校验查询结果
    if not order:
        return jsonify(errno=RET.REQERR, errmsg="操作无效")
    #尝试保存订单评价信息
    try:
        order.status = "COMPLETE"
        order.comment = comment
        #把订单成交数加1
        house.order_count += 1
        db.session.add(order)
        db.session.add(house)
        db.session.commit()
    except Exception as e:
        #如果发生异常信息，记录日志，进行回滚操作
        current_app.logger.error(e)
        db.session.rollback()
        return jsonify(errno=RET.DBERR, errmsg="操作失败")
    #删除缓存数据库中存储的房屋信息，房屋已完成交易，缓存中的数据已描述不准确
    try:
        redis_store.delete("house_info_%s" % order.house.id)
    except Exception as e:
        current_app.logger.error(e)
    #返回前端响应结果
    return jsonify(errno=RET.OK, errmsg="OK")
