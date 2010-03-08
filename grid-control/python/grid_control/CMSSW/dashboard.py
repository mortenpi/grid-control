import os, threading
from grid_control import utils, Monitoring
from time import localtime, strftime
from DashboardAPI import DashboardAPI

class DashBoardMonitoring(Monitoring):
	def __init__(self, config, module):
		Monitoring.__init__(self, config, module)
		self.app = config.get('dashboard', 'application', 'shellscript', volatile=True)
		self.tasktype = config.get('dashboard', 'task', 'analysis', volatile=True)


	def getEnv(self, wms):
		return { 'TASK_USER': wms.proxy.getUsername(), 'DASHBOARD': 'yes' }


	def getFiles(self):
		for file in ('DashboardAPI.py', 'Logger.py', 'ProcInfo.py', 'apmon.py', 'report.py'):
			yield utils.atRoot('python/DashboardAPI', file)


	def publish(self, jobObj, jobNum, usermsg):
		dashId = "%s_%s" % (jobNum, jobObj.wmsId)
		dashboard = DashboardAPI(self.module.taskID, dashId)
		msg = { "taskId": self.module.taskID, "jobId": dashId, "sid": dashId }
		msg = dict(filter(lambda (x, y): y != None, reduce(lambda x, y: x+y, map(dict.items, [msg] + usermsg))))
		dashboard.publish(**msg)


	# Called on job submission
	def onJobSubmit(self, wms, jobObj, jobNum):
		Monitoring.onJobSubmit(self, wms, jobObj, jobNum)
		threading.Thread(target = self.publish, args = (jobObj, jobNum, [{
			"user": os.environ['LOGNAME'], "GridName": wms.proxy.getUsername(),
			"tool": "grid-control", "JSToolVersion": utils.getVersion(),
			"application": self.app, "exe": "shellscript", "taskType": self.tasktype,
			"scheduler": "gLite", "vo": wms.proxy.getVO()}] +
			[self.module.getSubmitInfo(jobNum)])).start()


	# Called on job status update
	def onJobUpdate(self, wms, jobObj, jobNum, data):
		Monitoring.onJobUpdate(self, wms, jobObj, jobNum, data)
		threading.Thread(target = self.publish, args = (jobObj, jobNum, [{
			"StatusValue": data.get('status', 'pending').upper(),
			"StatusValueReason": data.get('reason', data.get('status', 'pending')).upper(),
			"StatusEnterTime": data.get('timestamp', strftime("%Y-%m-%d_%H:%M:%S", localtime())),
			"StatusDestination": data.get('dest', "") }],)).start()
