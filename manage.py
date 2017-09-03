#!/usr/bin/env python
# -*- coding:utf-8 -*-

from ihome import create_app, db
from flask_script import Manager
from flask_migrate import Migrate, MigrateCommand

#调用create_app方法，创建应用程序实例，指定开发者模式
app = create_app("development")

Migrate(app, db)
manager = Manager(app)
manager.add_command("db", MigrateCommand)


if __name__ == '__main__':
    manager.run()

