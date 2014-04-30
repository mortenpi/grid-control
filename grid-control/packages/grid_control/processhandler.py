#-#  Copyright 2013-2014 Karlsruhe Institute of Technology
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

import sys, os, stat, time, popen2, math
from exceptions import *

from abstract import LoadableObject
from utils import LoggedProcess, eprint, vprint, resolveInstallPath

# placeholder for function arguments
defaultArg = object()


################################
# Process Handlers
# create interface for initializing a set of commands sharing a similar setup, e.g. remote commands through SSH

# Process Handler:
class ProcessHandler(LoadableObject):
	def LoggedProcess(self, cmd, args = '', **kwargs):
		raise AbstractError
	def LoggedCopyToRemote(self, source, dest, **kwargs):
		raise AbstractError
	def LoggedCopyFromRemote(self, source, dest, **kwargs):
		raise AbstractError
	def getDomain(self):
		raise AbstractError
	
# local Processes - ensures uniform interfacing as with remote connections
class LocalProcessHandler(ProcessHandler):
	cpy="cp -r"
	def __init__(self, **kwargs):
		pass
	# return instance of LoggedProcess with input properly wrapped
	def LoggedProcess(self, cmd, args = '', **kwargs):
		return LoggedProcess( cmd , args )

	def LoggedCopyToRemote(self, source, dest, **kwargs):
		return LoggedProcess( self.cpy, " ".join([source, dest]) )

	def LoggedCopyFromRemote(self, source, dest, **kwargs):
		return LoggedProcess( self.cpy, " ".join([source, dest]) )

	def getDomain(self):
		return "localhost"


# remote Processes via SSH
class SSHProcessHandler(ProcessHandler):
	# track lifetime and quality of command socket
	socketTimestamp=0
	socketFailCount=0
	# older versions of ssh/gsissh will propagate an end of master incorrectly to children - rotate sockets
	socketIdNow=0
	def __init__(self, **kwargs):
		self.__initcommands(**kwargs)
		self.defaultArgs="-vvv -o BatchMode=yes  -o ForwardX11=no " + kwargs.get("defaultArgs","")
		self.socketArgs=""
		self.socketEnforce=kwargs.get("sshLinkEnforce",True)
		try:
			self.remoteHost = kwargs["remoteHost"]
			if not self.remoteHost:
				raise RuntimeError("No Host")
		except Exception:
			raise RethrowError("Request to initialize SSH-Type RemoteProcessHandler without remote host.")
		try:
			self.sshLinkBase=os.path.abspath(kwargs["sshLink"])
			# older ssh/gsissh puts a maximum length limit on control paths...
			if ( len(self.sshLinkBase)>= 107):
				self.sshLinkBase=os.path.expanduser("~/.ssh/%s"%os.path.basename(self.sshLinkBase))
			self.sshLink=self.sshLinkBase
			self._secureSSHLink(initDirectory=True)
			self._socketHandler()
		except KeyError:
			self.sshLink=False
		# test connection once
		testProcess = self.LoggedProcess( "exit" )
		if testProcess.wait() != 0:
			raise RuntimeError("Failed to validate remote connection.\n	Command: %s Return code: %s\n%s" % ( testProcess.cmd, testProcess.wait(), testProcess.getOutput() ) )
	def __initcommands(self, **kwargs):
		self.cmd = resolveInstallPath("ssh")
		self.cpy = resolveInstallPath("scp") + " -r"

	# return instance of LoggedProcess with input properly wrapped
	def LoggedProcess(self, cmd, args = '', **kwargs):
		self._socketHandler()
		return LoggedProcess( " ".join([self.cmd, self.defaultArgs, self.socketArgs, kwargs.get('handlerArgs',""), self.remoteHost, self._argFormat(cmd + " " + args)]) )
	def _SocketProcess(self, cmd, args = '', **kwargs):
		return LoggedProcess( " ".join([self.cmd, self.defaultArgs, self.socketArgsDef, kwargs.get('handlerArgs',""), self.remoteHost, self._argFormat(cmd + " " + args)]) )
	def LoggedCopyToRemote(self, source, dest, **kwargs):
		self._socketHandler()
		return LoggedProcess( " ".join([self.cpy, self.defaultArgs, self.socketArgs, kwargs.get('handlerArgs',""), source, self._remotePath(dest)]) )
	def LoggedCopyFromRemote(self, source, dest, **kwargs):
		self._socketHandler()
		return LoggedProcess( " ".join([self.cpy, self.defaultArgs, self.socketArgs, kwargs.get('handlerArgs',""), self._remotePath(source), dest]) )

	def getDomain(self):
		return self.remoteHost

	# Helper functions
	def _argFormat(self, args):
		return "'" + args.replace("'", "'\\''") + "'"
	def _remotePath(self, path):
		return "%s:%s" % (self.remoteHost,path)

	# handler for creating, validating and publishing/denying ssh link socket
	def _socketHandler(self, maxFailCount=5):
		if self.sshLink:
			if self._refreshSSHLink():
				if self.socketArgs!=self.socketArgsDef:
					self.socketArgs=self.socketArgsDef
			else:
				self.socketFailCount+=1
				if self.socketArgs!="":
					self.socketArgs=""
				if self.socketFailCount>maxFailCount:
					eprint("Failed to create secure socket %s more than %s times!\nDisabling further attempts." % (self.sshLink,maxFailCount))
					self.sshLink=False

	# make sure the link file is properly protected
	# 	@sshLink:	location of the link
	#	@directory:	secure only directory (for initializing)
	def _secureSSHLink(self, initDirectory=False):
		sshLink=os.path.abspath(self.sshLink)
		sshLinkDir=os.path.dirname(self.sshLink)
		# containing directory should be secure
		if not os.path.isdir(sshLinkDir):
			try:
				os.makedirs(sshLinkDir)
			except Exception:
				if self.socketEnforce:
					raise RethrowError("Could not create or access directory for SSHLink:\n	%s" % sshLinkDir)
				else:
					return False
		if initDirectory:
			return True
		if sshLinkDir!=os.path.dirname(os.path.expanduser("~/.ssh/")):
			try:
				os.chmod(sshLinkDir,0700)
			except Exception:
				RethrowError("Could not secure directory for SSHLink:\n	%s" % sshLinkDir)
		# socket link object should be secure against manipulation if it exists
		if os.path.exists(sshLink):
			if stat.S_ISSOCK(os.stat(sshLink).st_mode):
				try:
					os.chmod(sshLink,0700)
				except Exception:
					if self.socketEnforce:
						raise RethrowError("Could not validate security of SSHLink:\n	%s\nThis is a potential security violation!" % sshLink)
					else:
						return False
			else:
				if self.socketEnforce:
					raise RuntimeError("Could not validate security of SSHLink:\n	%s\nThis is a potential security violation!" % sshLink)
				else:
					return False
		return True

	# keep a process active in the background to speed up connecting by providing an active socket
	def _refreshSSHLink(self, minSeconds=120, maxSeconds=600):
		# if there is a link, ensure it'll still live for minimum lifetime
		if os.path.exists(self.sshLink) and stat.S_ISSOCK(os.stat(self.sshLink).st_mode):
			if ( time.time() - self.socketTimestamp < maxSeconds-minSeconds ):
				return True
		# rotate socket
		self.socketIdNow = (self.socketIdNow + 1) % (math.ceil(1.0*maxSeconds/(maxSeconds-minSeconds)) + 1)
		self.sshLink = self.sshLinkBase+str(self.socketIdNow)
		self.socketArgsDef = " -o ControlMaster=auto  -o ControlPath=" + self.sshLink + " "
		if os.path.exists(self.sshLink):
			os.remove(self.sshLink)
		# send a dummy background process over ssh to keep the connection going
		socketProc = self._SocketProcess("sleep %s" % maxSeconds)
		timeout = 0
		while not os.path.exists(self.sshLink):
			time.sleep(0.5)
			timeout += 0.5
			if timeout == 6:
				vprint("SSH socket still not available after 6 seconds...\n%s" % self.sshLink, level=1)
				vprint('Socket process: %s' % (socketProc.cmd), level=2)
			if timeout == 10:
				return False
		self.socketTimestamp = time.time()
		return self._secureSSHLink()

# remote Processes via GSISSH
class GSISSHProcessHandler(SSHProcessHandler):
	# commands to use - overwritten by inheriting class
	def __initcommands(self, **kwargs):
		cmd = resolveInstallPath("gsissh")
		cpy = resolveInstallPath("gsiscp") + " -r"

ProcessHandler.registerObject()
