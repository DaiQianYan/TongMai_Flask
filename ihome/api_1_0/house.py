# -*- coding:utf-8 -*-

import json
import datetime

from flask import current_app, request, jsonify, g, session
from ihome import db, redis_store, constants
from ihome.utils.response_code import RET
from ihome.utils.commons import login_required
from ihome.utils.image_storage import storage
from ihome.models import Area, House, Facility, HouseImage, User, Order
from . import api
#获取城区信息
@api.route("/areas", methods=["GET"])
def get_areas_info():
    """
    1、接收参数
    2、校验参数
    3、查询数据库
    4、返回结果
    """
    #查询缓存数据库，获取城区信息
    try:
        areas = redis_store.get("area_info")
    except Exception as e:
        current_app.logger.error(e)
        areas = None
    #如果获取到城区信息，把数据返回给前端
    if areas:
        current_app.logger.info("hit area info redis")
        #由于缓存中存储的城区数据，格式为json字符串，所以可以直接返回给前端
        return '{"errno":0, "errmsg":"OK", "data":%s}' % areas
    #如果没有获取到城区数据，需要查询mysql数据库
    try:
        areas = Area.query.all()
    except Exception as e:
        current_app.logger.error(e)
        #如果查询数据发生异常，返回错误信息给前端
        return jsonify(errno=RET.DBERR, errmsg="获取城区信息失败") 
    #定义列表，用来存储mysql数据中查询到的城区信息数据，并把数据转换成json字符串，返回前端
    areas_list = []
    for area in areas:
        areas_list.append(area.to_dict())
    json_areas = json.dumps(areas_list)
    #把查询结果，添加到缓存数据库中
    try:
        redis_store.setex("area_info", constants.AREA_INFO_REDIS_EXPIRES, json_areas)
    except Exception as e:
        current_app.logger.error(e)
    #返回前端城区信息数据
    resp = '{"errno":"0", "errmsg":"OK", "data":%s}' % json_areas
    return resp

@api.route("/houses", methods=["POST"])
@login_required
def save_new_house():
    """
    房东发布新房源
    1、接收参数
    2、校验参数
    3、查询数据库
    4、返回结果
    """
    """
    {
        "title":"",
        "price":"",
        "area_id":"1",
        "address":"",
        "room_count":"",
        "acreage":"",
        "unit":"",
        "capacity":"",
        "beds":"",
        "deposit":"",
        "min_days":"",
        "max_days":"",
        "facility":["7","8"]
    }
    """
    #获取用户编号
    user_id = g.user_id 
    #获取请求参数  
    house_data = request.get_json()
    #首先判断参数是否存在
    if house_data is None:
        return jsonify(errno=RET.PARAMERR, errmsg="参数缺失")
    #进一步获取房屋的详细描述信息
    title = house_data.get("title")  # 房屋名称标题
    price = house_data.get("price")  # 房屋单价
    area_id = house_data.get("area_id")  # 房屋所属城区的编号
    address = house_data.get("address")  # 房屋地址
    room_count = house_data.get("room_count")  # 房屋包含的房间数目
    acreage = house_data.get("acreage")  # 房屋面积
    unit = house_data.get("unit")  # 房屋布局（几室几厅)
    capacity = house_data.get("capacity")  # 房屋容纳人数
    beds = house_data.get("beds")  # 房屋卧床数目
    deposit = house_data.get("deposit")  # 押金
    min_days = house_data.get("min_days")  # 最小入住天数
    max_days = house_data.get("max_days")  # 最大入住天数
    #校验房屋信息的完整性
    if not all((title, price, area_id, address, room_count, acreage, unit, capacity, beds, deposit, min_days,
                max_days)):
        return jsonify(errno=RET.PARAMERR, errmsg="参数缺失")
    #把价格由元转换为分，为了确保金额的准确性
    try:
        price = int(float(price) * 100)
        deposit = int(float(deposit) * 100)
    except Exception as e:
        return jsonify(errno=RET.PARAMERR, errmsg="参数错误")
    #保存用户输入的房屋信息
    house = House()
    house.user_id = user_id
    house.area_id = area_id
    house.title = title
    house.price = price
    house.address = address
    house.room_count = room_count
    house.acreage = acreage
    house.unit = unit
    house.capacity = capacity
    house.beds = beds
    house.deposit = deposit
    house.min_days = min_days
    house.max_days = max_days

    #获取设施信息
    facility = house_data.get("facility")
    if facility:
        #过滤设施信息，只存储数据库中定义的设施信息
        facilities = Facility.query.filter(Facility.id.in_(facility)).all()
        house.facilities = facilities
    #把数据存入到数据库中
    try:
        db.session.add(house)
        db.session.commit()
    except Exception as e:
        current_app.logger.error(e)
        #如果存入数据失败，进行回滚操作
        db.session.rollback()
        return jsonify(errno=RET.DBERR, errmsg="保存房屋数据失败")
    #返回前端正确的响应数据
    return jsonify(errno=RET.OK, errmsg="OK", data={"house_id": house.id})


@api.route("/houses/<int:house_id>/images", methods=["POST"])
@login_required
def save_house_image(house_id):
    """
    上传房屋图片
    1、接收参数
    2、校验参数
    3、查询数据库
    4、返回结果
    """
    #获取房屋图片信息
    image = request.files.get("house_image")
    #如果没有图片信息
    if not image:
        return jsonify(errno=RET.PARAMERR, errmsg="未传图片")
    #首先查询数据库，获取房屋信息
    try:
        house = House.query.get(house_id)
    except Exception as e:
        current_app.logger.error(e)
        return jsonify(errno=RET.DATAERR, errmsg="房屋不存在")
    #读取图片文件
    image_data = image.read()
    #调用第三方七牛云接口，获取图片路径（图片名称）
    try:
        image_name = storage(image_data)
    except Exception as e:
        current_app.logger.error(e)
        return jsonify(errno=RET.THIRDERR, errmsg="上传图片失败")
    #把图片名称临时加入到数据库的session对象中
    house_image = HouseImage()
    house_image.house_id = house_id
    house_image.url = image_name
    db.session.add(house_image)
    #设施房屋的主图片信息
    if not house.index_image_url:
        house.index_image_url = image_name
        db.session.add(house)
    #把图片数据存入数据库
    try:
        db.session.commit()
    except Exception as e:
        current_app.logger.error(e)
        db.session.rollback()
        return jsonify(errno=RET.DBERR, errmsg="保存房屋图片失败")
    #拼接房屋图片的url，并且把响应数据返回给前端
    img_url = constants.QINIU_DOMIN_PREFIX + image_name
    return jsonify(errno=RET.OK, errmsg="OK", data={"url": img_url})


@api.route("/user/houses", methods=["GET"])
@login_required
def get_user_houses():
     """
    获取用户房源列表
    1、接收参数
    2、校验参数
    3、查询数据库
    4、返回结果
    """
    # 获取用户编号
    user_id = g.user_id
    # 根据用户编号，查询数据库中存储的房屋数据
    try:
        user = User.query.get(user_id)
        houses = user.houses
    except Exception as e:
        current_app.logger.error(e)
        return jsonify(errno=RET.DBERR, errmsg="获取数据失败")
    #把查询结果存储到列表中，
    houses_list = []
    if houses:
        for house in houses:
            #调用了房屋模型类的序列化数据的方法to_basic_dict()
            houses_list.append(house.to_basic_dict())
    #把房屋列表信息返回给前端
    return jsonify(errno=RET.OK, errmsg="OK", data={"houses": houses_list})



@api.route("/houses/index", methods=["GET"])
def get_house_index():
    """项目首页信息展示"""
    #尝试从缓存数据库中获取房源信息
    try:
        ret = redis_store.get("home_page_data")
    except Exception as e:
        current_app.logger.error(e)
        ret = None
    #如果获取到房源信息数据，记录下日志，便于查看房源信息的过期时间
    if ret:
        current_app.logger.info("hit house index info redis")
        return '{"errno":0, "errmsg":"OK", "data":%s}' % ret
    #如果缓存中没有数据，需要查询mysql数据库，默认展示五条成交量最高的房源信息，按倒叙排列
    else:
        try:
            houses = House.query.order_by(House.order_count.desc()).limit(constants.HOME_PAGE_MAX_HOUSES)
        except Exception as e:
            current_app.logger.error(e)
            return jsonify(errno=RET.DBERR, errmsg="查询数据失败")
        #校验查询结果
        if not houses:
            return jsonify(errno=RET.NODATA, errmsg="查询无数据")
        #定义一个列表用来存储查询到数据
        houses_list = []
        for house in houses:
            #如果房源信息里，没有房源图片信息
            if not house.index_image_url:
                continue
            #把遍历的结果添加到列表中，序列化数据调用了模型类中的to_basic_dict()方法
            houses_list.append(house.to_basic_dict())
        #转换成json
        json_houses = json.dumps(houses_list)
        #把响应数据先存储到缓存数据库中
        try:
            redis_store.setex("home_page_data", constants.HOME_PAGE_DATA_REDIS_EXPIRES, json_houses)
        except Exception as e:
            current_app.logger.error(e)
        #返回响应数据给前端
        return '{"errno":0, "errmsg":"OK", "data":%s}' % json_houses


@api.route("/houses/<int:house_id>", methods=["GET"])
def get_house_detail(house_id):
    """房间详情信息展示"""
    #首先需要判断用户是否是房东，如果不是房东，提供预定接口，如果是，隐藏预定接口
    #获取用户id值，用来前端判断用户是否为房东
    user_id = session.get("user_id", "-1")
    #校验房屋id
    if not house_id:
        return jsonify(errno=RET.PARAMERR, errmsg="参数缺失")
    #尝试从redis缓存数据库中，根据房屋id获取房屋信息
    try:
        ret = redis_store.get("house_info_%s" % house_id)
    except Exception as e:
        current_app.logger.error(e)
        ret = None
    #如果获取到房屋信息数据
    if ret:
        current_app.logger.info("hit house info redis")
        return '{"errno":"0", "errmsg":"OK", "data":{"user_id":%s, "house":%s}}' % (user_id, ret)
    #如果缓存中没有获取到数据，查询mysql数据库
    try:
        house = House.query.get(house_id)
    except Exception as e:
        current_app.logger.error(e)
        #如果数据库中，没有具体的房屋信息，需要终止视图函数的执行
        return jsonify(errno=RET.DBERR, errmsg="查询数据失败")
    #校验参数是否存在
    if not house:
        return jsonify(errno=RET.NODATA, errmsg="房屋不存在")
    #如果房屋信息已经获取，调用了模型类中的to_full_dict()方法，用来展示详细的房屋信息
    try:
        house_data = house.to_full_dict()
    except Exception as e:
        current_app.logger.error(e)
        return jsonify(errno=RET.DATAERR, errmsg="数据出错")
    #把序列化后的数据，转成json，先把数据缓存到redis中，然后返回给前端
    json_house = json.dumps(house_data)
    try:
        redis_store.setex("house_info_%s" % house_id, constants.HOUSE_DETAIL_REDIS_EXPIRE_SECOND, json_house)
    except Exception as e:
        current_app.logger.error(e)
    resp = '{"errno":"0", "errmsg":"OK", "data":{"user_id":%s, "house":%s}}' % (user_id, json_house)
    #把响应数据返回给前端
    return resp


@api.route("/houses", methods=["GET"])
def get_houses_list(): 
    """房屋分页信息展示"""
    #获取参数
    area_id = request.args.get("aid", "") #房屋区域id
    start_date_str = request.args.get("sd", "") #用户选择的开始日期
    end_date_str = request.args.get("ed", "") #结束日期
    sort_key = request.args.get("sk", "new") #排序
    page = request.args.get("p", "1")  #页数
    #首先要对日期进行数据转换，从url中传参是str类型
    try:
        start_date, end_date = None, None
        #把str类型的日期，转换格式
        if start_date_str:
            start_date = datetime.datetime.strptime(start_date_str, "%Y-%m-%d")
        if end_date_str:
            end_date = datetime.datetime.strptime(end_date_str, "%Y-%m-%d")
        #校验参数，对日期进行判断
        if start_date_str and end_date_str:
            assert start_date <= end_date
    except Exception as e:
        #如果出现异常，记录异常信息，并返回响应结果
        current_app.logger.error(e)
        return jsonify(errno=RET.PARAMERR, errmsg="日期格式不正确")
    #校验参数，对页数进行数据转换
    try:
        page = int(page)
    except Exception as e:
        current_app.logger.error(e)
        return jsonify(errno=RET.PARAMERR, errmsg="页数格式不正确")
    #尝试获取数据，从redis缓存中获取房源信息数据，使用的数据为哈希类型
    try:
        redis_key = "houses_%s_%s_%s_%s" % (area_id, start_date_str, end_date_str, sort_key)
        ret = redis_store.hget(redis_key, page)
    except Exception as e:
        #如果没有获取到数据，记录日志信息
        current_app.logger.error(e)
        #即使发生异常，把查询结果值为None，而不能终止视图函数的执行，后面需要继续查询数据库
        ret = None
    #如果从redis缓存数据库中，获取到了数据
    if ret:
        current_app.logger.info("hit houses list redis")
        return ret
    #查询mysql数据库
    try:
        #定义变量，用来存储过滤条件
        filter_params = []
        #首先判断区域id
        if area_id:
            filter_params.append(House.area_id == area_id)
        #对日期进行校验，过滤所有不满足条件的数据
        if start_date and end_date:            
            conflict_orders = Order.query.filter(Order.begin_date <= end_date, Order.end_date >= start_date).all()
            conflict_houses_ids = [order.house_id for order in conflict_orders]
            if conflict_houses_ids:
                filter_params.append(House.id.notin_(conflict_houses_ids))
        #过滤掉所有不符合条件的数据
        elif start_date:
            conflict_orders = Order.query.filter(Order.end_date >= start_date).all()
            conflict_houses_ids = [order.house_id for order in conflict_orders]
            if conflict_houses_ids:
                filter_params.append(House.id.notin_(conflict_houses_ids))
        elif end_date:
            conflict_orders = Order.query.filter(Order.begin_date <= end_date).all()
            conflict_houses_ids = [order.house_id for order in conflict_orders]
            if conflict_houses_ids:
                filter_params.append(House.id.notin_(conflict_houses_ids))
        #按成交量排序、价格排序
        if "booking" == sort_key:
            houses = House.query.filter(*filter_params).order_by(House.order_count.desc()) 
        elif "price-inc" == sort_key:
            houses = House.query.filter(*filter_params).order_by(House.price.asc())
        elif "price-des" == sort_key:
            houses = House.query.filter(*filter_params).order_by(House.price.desc())
        #如果用户没有传递参数，默认按房源的创建时间进行排序
        else:
            houses = House.query.filter(*filter_params).order_by(House.create_time.desc())
        #根据参数进行排序，paginate进行分页，保留房源信息和房源页数
        houses_page = houses.paginate(page, constants.HOUSE_LIST_PAGE_CAPACITY, False)
        houses_list = houses_page.items
        total_page = houses_page.pages
        #定义变量，用来保存房源信息
        houses_dict_list = []
        for house in houses_list:
            houses_dict_list.append(house.to_basic_dict())
    except Exception as e:
        #如果发生异常，直接返回异常信息，整个把区域id、日期、排序条件、分页整体判断
        current_app.logger.error(e)
        return jsonify(errno=RET.DBERR, errmsg="查询数据失败")
    #构造响应数据，返回前端
    resp = {"errno": RET.OK, "errmsg": "OK", "data": {"houses": houses_dict_list,
                                                      "total_page": total_page, "current_page": page}}
    #把响应数据转成json
    resp_json = json.dumps(resp)
    if page <= total_page:
        redis_key = "houses_%s_%s_%s_%s" % (area_id, start_date_str, end_date_str, sort_key)
        #通过redis的pipeline()，实现对redis多条数据的事务操作
        pipe = redis_store.pipeline()
        try: 
            #对多条数据进行缓存操作，统一设置过期时间
            pipe.multi()
            pipe.hset(redis_key, page, resp_json)
            pipe.expire(redis_key, constants.HOME_PAGE_DATA_REDIS_EXPIRES)
            pipe.execute()
        except Exception as e:
            current_app.logger.error(e)
    #把响应结果返回前端
    return resp_json
