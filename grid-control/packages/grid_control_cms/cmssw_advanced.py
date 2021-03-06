#-#  Copyright 2010-2014 Karlsruhe Institute of Technology
#-#
#-#  Licensed under the Apache License, Version 2.0 (the "License");
#-#  you may not use this file except in compliance with the License.
#-#  You may obtain a copy of the License at
#-#
#-#      http://www.apache.org/licenses/LICENSE-2.0
#-#
#-#  Unless required by applicable law or agreed to in writing, software
#-#  distributed under the License is distributed on an "AS IS" BASIS,
#-#  WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#-#  See the License for the specific language governing permissions and
#-#  limitations under the License.

import os, re, cmssw
from python_compat import set, sorted
from grid_control import datasets, utils, ConfigError
from grid_control.datasets import DataSplitter, DataProvider
from lumi_tools import *

def fromNM(nm, nickname, default):
	tmp = filter(lambda p: p and nickname and re.search(p, nickname), nm)
	if len(tmp)>0:
		return map(lambda pattern: nm[pattern], tmp)
	return [nm.get(None, default)]

class CMSSW_Advanced(cmssw.CMSSW):
	getConfigSections = cmssw.CMSSW.createFunction_getConfigSections(['CMSSW_Advanced'])

	def __init__(self, config, name):
		head = [(0, 'Nickname')]

		# Mapping between nickname and config files:
		cfgList = config.get('nickname config', '')
		self.nmCfg = config.getDict('nickname config', {},
			parser = lambda x: map(str.strip, x.split(',')), str = lambda x: str.join(',', x))[0]
		if cfgList:
			if 'config file' in config.getOptions():
				raise ConfigError("Please use 'nickname config' instead of 'config file'")
			allConfigFiles = utils.flatten(self.nmCfg.values())
			config.set('config file', str.join('\n', allConfigFiles))
			head.append((1, 'Config file'))

		# Mapping between nickname and constants:
		self.nmCName = map(str.strip, config.get('nickname constants', '').split())
		self.nmConst = {}
		for var in self.nmCName:
			tmp = config.getDict(var, {})[0]
			for (nick, value) in tmp.items():
				if value:
					self.nmConst.setdefault(nick, {})[var] = value
				else:
					self.nmConst.setdefault(nick, {})[var] = ''
			head.append((var, var))

		# Mapping between nickname and lumi filter:
		if 'lumi filter' in config.getOptions():
			raise ConfigError("Please use 'nickname lumi filter' instead of 'lumi filter'")
		lumiParse = lambda x: formatLumi(parseLumiFilter(x))
		self.nmLumi = config.getDict('nickname lumi filter', {}, parser = lumiParse)[0]
		if self.nmLumi:
			for dataset in config.get('dataset', '').splitlines():
				(datasetNick, datasetProvider, datasetExpr) = DataProvider.parseDatasetExpr(config, dataset, None)
				config.set('dataset %s' % datasetNick, 'lumi filter', str.join(',', utils.flatten(fromNM(self.nmLumi, datasetNick, []))))
			config.set('lumi filter', str.join(',', self.nmLumi.get(None, [])))
			head.append((2, 'Lumi filter'))

		utils.vprint('Mapping between nickname and other settings:\n', -1)
		def report():
			for nick in sorted(set(self.nmCfg.keys() + self.nmConst.keys() + self.nmLumi.keys())):
				tmp = {0: nick, 1: str.join(', ', map(os.path.basename, self.nmCfg.get(nick, ''))),
					2: self.displayLumi(self.nmLumi.get(nick, '')) }
				yield utils.mergeDicts([tmp, self.nmConst.get(nick, {})])
		utils.printTabular(head, report(), 'cl')
		utils.vprint(level = -1)
		cmssw.CMSSW.__init__(self, config, name)


	def displayLumi(self, lumi):
		if len(lumi) > 4:
			return '%s ... %s (%d entries)' % (lumi[0], lumi[-1], len(lumi))
		else:
			return str.join(', ', lumi)


	def getDatasetOverviewInfo(self, blocks):
		(head, blockInfos, fmt) = cmssw.CMSSW.getDatasetOverviewInfo(self, blocks)
		head.extend([('CMSSW_CONFIG', 'Config file'), ('LUMI_RANGE', 'Lumi filter')])
		def fmtLR(x):
			if x:
				return self.displayLumi(formatLumi(x))
			return x
		fmt['LUMI_RANGE'] = fmtLR
		for blockInfo in blockInfos:
			data = self.getVarsForNick(blockInfo.get(DataProvider.Nickname, None))
			for key in filter(lambda k: k not in ['CMSSW_CONFIG', 'LUMI_RANGE'], data.keys()):
				if (key, key) not in head:
					head.append((key, key))
			blockInfo.update(data)
		return (head, blockInfos, fmt)


	def neededVars(self):
		if self.nmLumi:
			return cmssw.CMSSW.neededVars(self) + ['LUMI_RANGE']
		return cmssw.CMSSW.neededVars(self)


	def getTaskConfig(self):
		# Remove config file variable from the global settings
		data = cmssw.CMSSW.getTaskConfig(self)
		data.pop('CMSSW_CONFIG')
		return data


	def getVarsForNick(self, nick):
		data = {'CMSSW_CONFIG': str.join(' ', map(os.path.basename, utils.flatten(fromNM(self.nmCfg, nick, ''))))}
		constants = utils.mergeDicts(fromNM(self.nmConst, None, {}) + fromNM(self.nmConst, nick, {}))
		constants = dict(map(lambda var: (var, constants.get(var, '')), self.nmCName))
		data.update(constants)
		lumifilter = utils.flatten(fromNM(self.nmLumi, nick, ''))
		if lumifilter:
			data['LUMI_RANGE'] = parseLumiFilter(str.join(',', lumifilter))
		return data


	def getJobConfig(self, jobNum):
		data = cmssw.CMSSW.getJobConfig(self, jobNum)
		nickdata = self.getVarsForNick(data.get('DATASETNICK'))
		data.update(nickdata)
		data['LUMI_RANGE'] = self.getActiveLumiFilter(data['LUMI_RANGE'], jobNum)
		if utils.verbosity() > 0:
			utils.vprint('Nickname: %s' % data.get('DATASETNICK'), 1)
			utils.vprint(' * Config files: %s' % data['CMSSW_CONFIG'], 1)
			utils.vprint(' *   Lumi range: %s' % data['LUMI_RANGE'], 1)
			utils.vprint(' *    Variables: %s' % utils.filterDict(nickdata, lambda k: k not in ['CMSSW_CONFIG', 'LUMI_RANGE']), 1)
		return data


	def getVarNames(self):
		return cmssw.CMSSW.getVarNames(self) + self.getJobConfig(0).keys()
