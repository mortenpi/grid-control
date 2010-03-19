from splitter_base import DataSplitter
from provider_base import DataProvider

class HybridSplitter(DataSplitter):
	def __init__(self, config, section, values):
		DataSplitter.__init__(self, config, section, values)
		self.set('eventsPerJob', config.getInt, 'events per job')


	def splitDatasetInternal(self, blocks, firstEvent = 0):
		for block in blocks:
			events = 0
			fileStack = []

			for fileInfo in block[DataProvider.FileList]:
				nextEvents = events + fileInfo[DataProvider.NEvents]
				if (len(fileStack) > 0) and (nextEvents > self.eventsPerJob):
					job[DataSplitter.Skipped] = 0
					job[DataSplitter.FileList] = fileStack
					job[DataSplitter.NEvents] = events
					yield self.cpBlockToJob(block, job)
					fileStack = []
					events = 0
				events += fileInfo[DataProvider.NEvents]
				fileStack += fileInfo

			job[DataSplitter.Skipped] = 0
			job[DataSplitter.FileList] = fileStack
			job[DataSplitter.NEvents] = events
			yield self.cpBlockToJob(block, job)
