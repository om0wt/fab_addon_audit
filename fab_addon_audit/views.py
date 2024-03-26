import copy
from loguru import logger as log
import json
from json2html import json2html
from collections import OrderedDict
from flask import render_template, g
from flask_appbuilder.models.sqla.interface import SQLAInterface
from flask_appbuilder.widgets import ListLinkWidget
from flask_appbuilder import ModelView
from flask_appbuilder.charts.views import DirectByChartView, GroupByChartView
from flask_appbuilder.models.group import aggregate_count, aggregate_avg, aggregate_sum
from .models import AuditLog, Operation

def asdict(item):
    result = OrderedDict()
    for key in item.__mapper__.attrs.keys():
        if getattr(item, key) is not None:
            result[key] = str(getattr(item, key))
        else:
            result[key] = getattr(item, key)
    return result


def compare_json(json1, json2):
    # Ensure both inputs are dictionaries
    if not isinstance(json1, dict) or not isinstance(json2, dict):
        raise ValueError("Both inputs must be dictionaries")
    
    # Initialize dictionary to store differences
    differences = {}

    # Compare keys in both JSON objects
    all_keys = sorted(set(json1.keys()) | set(json2.keys()))
    for key in all_keys:
        val1 = json1.get(key)
        val2 = json2.get(key)

        # Sync True/False values
        val2 = (0 if val2 == "False" else val2)
        val1 = (0 if val1 == "False" else val1)

        val2 = (1 if val2 == "True" else val2)
        val1 = (1 if val1 == "True" else val1)
        
        if str(val1) != str(val2) and val1 is not None and val2 is not None:
            differences[key] = {"New value": val1, "Old value": val2}

    return differences


class AuditedModelView(ModelView):

    old_target_values = None
    
    def update_operation(self):
        return self.appbuilder.get_session.query(Operation).filter(Operation.name == 'UPDATE').first()

    def insert_operation(self):
        return self.appbuilder.get_session.query(Operation).filter(Operation.name == 'INSERT').first()

    def delete_operation(self):
        return self.appbuilder.get_session.query(Operation).filter(Operation.name == 'DELETE').first()

    def add_log_event(self, message, operation, target_values=None):
        auditlog = AuditLog(message=message, username=g.user.username, operation=operation, target=self.__class__.__name__, target_values=target_values)
        try:
            self.appbuilder.get_session.add(auditlog)
            self.appbuilder.get_session.commit()
        except Exception as e:
            log.error("Unable to write audit log for post_update")
            self.appbuilder.get_session.rollback()

    def pre_update(self, item, old_item=None):
        if old_item is not None:
            self.old_target_values = old_item
        else:
            # Nothing to compare with
            self.old_target_values = item

    def post_update(self, item):
        operation = self.update_operation()
        compare_new_old_item_values = json.dumps(compare_json(asdict(item), self.old_target_values), indent=4)
        new_old_values_table = json2html.convert(json=compare_new_old_item_values, table_attributes="class=\"table table-bordered table-hover\"", escape=True)
        self.add_log_event(str(item), operation, new_old_values_table)

    def post_add(self, item):
        operation = self.insert_operation()
        target_values = json.dumps(asdict(item), sort_keys=True, indent=4)
        self.add_log_event(str(item), operation, target_values)

    def post_delete(self, item):
        operation = self.delete_operation()
        target_values = json.dumps(asdict(item), sort_keys=True, indent=4)
        self.add_log_event(str(item), operation, target_values)


class AuditLogView(ModelView):
    datamodel = SQLAInterface(AuditLog)
    base_order = ("created_on", "desc")
    list_widget = ListLinkWidget
    list_columns = ['created_on', 'username', 'operation.name', 'target', 'message']
    base_permissions = ['can_list','can_show']
    show_fields = ['operation.name', 'message', "username", 'created_on', 'target', 'target_values'] 

class AuditLogChartView(GroupByChartView):
    datamodel = SQLAInterface(AuditLog)

    chart_title = 'Grouped Audit Logs'
    chart_type = 'BarChart'
    definitions = [
        {
            'group' : 'operation.name',
            'formatter': str,
            'series': [(aggregate_count,'operation')]
        },
        {
            'group' : 'username',
            'formatter': str,
            'series': [(aggregate_count,'username')]
        },
        {
            'group' : 'target',
            'formatter': str,
            'series': [(aggregate_count,'target')]
        }
    ]

