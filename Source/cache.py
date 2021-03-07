import collections, enum
from Source.utils import *
from Source.tracker import Tracker
# import logging as log 

class LineState(enum.Enum):
    """Class holding possible states of a cache

    Args:
        enum (class): using the Enum class to create enumarations

    Returns:
        [Enum]: possible LineState
    """
    MODIFIED, SHARED, INVALID = range(3)                                    # MSI --> 012
 
    def to_str(self,state):
        if(state==LineState.MODIFIED):
            return "MODIFIED"
        if(state==LineState.SHARED):
            return "SHARED"
        if(state==LineState.INVALID):
            return "INVALID"
        else:
            raise ValueError("Invalide state type: {}".format(state))

class CacheLine():
    """Class representing a line inside the Cache.
    Keeps track of the address tag and state of the Cache Line
    """
    def __init__(self):
        self.address_tag, self._lastState, self._currentState, self.written = None, None, LineState.INVALID, False
    
    @property
    def currentState(self):
        return self._currentState
    
    @currentState.setter
    def currentState(self,new_state):
        self._lastState = self._currentState
        self._currentState = new_state
    
    @property
    def lastState(self):
        return self._lastState
    
    def __repr__(self):
        return '[tag={};written={},state_now={},state_before={}]'.format(
            self.address_tag, self.written, self.currentState, self.lastState)

class Cache():

    def __init__(self, tracker:Tracker, memory_controller, id:int, cache_lines:int, cache_line_size:int, logger_):
        
        self.log = logger_
        self.id, self.cache_lines, self.cache_line_size = id, cache_lines, cache_line_size
        self._check_vaid_cache()                                                                    # make sure valid params
        self.memory_controller = memory_controller                                                  # reference  memory controller
        self.memory_controller.add_cache(self)                                                      # add cache to memory
        self.tracker = tracker                                                                      # reference tracker
        self.lines = collections.defaultdict(CacheLine)                                             # dictionary collecction of cache lines
        

    def _check_vaid_cache(self):
        """Cehck if cache parameters are valid and get proper bit length if so.

        Raises:
            ValueError: if number of cache lines of size of cache line is not power of 2
        """
        if (not is_valid_int(self.cache_lines)) or (not is_valid_int(self.cache_line_size)):
            raise ValueError('Cache line size and number must be powers of 2')
        

    def __repr__(self):
        return 'id: {}; nr lines: {}; line size: {}'.format(self.id, len(self.lines), 4)

        
    def read(self, address:int):
        """Read instruction given to cache

        Args:
            address (int): current address

        Raises:
            ValueError: cache line in a incorrect state

        Returns:
            bool: True if hit, False otherwise
        """
        
        # -- probe cache to match tag and check state
        tag, line_id, offset = self._probe_cache(address=address)
        cache_line = self.lines[line_id]                                                            # cache line from addresss
        # -- check if tag hit
        tag_hit = (tag==cache_line.address_tag)                                                     # do tags match
        # -- check if it's a replacement writeback
        if(tag!=cache_line.address_tag and cache_line.currentState==LineState.MODIFIED):
            self.tracker.replacement_writebacks_i = 1
        # -- check line state
        if (cache_line.currentState==LineState.INVALID) or (tag_hit==False):                        # line is Invalid --> miss
            # -- memory request data to read
            self._read_request_data(cache_line=cache_line, address=address)
            # -- probe cache to change state
            self._probe_cache(address=address)
            cache_line.currentState  = LineState.SHARED
            cache_line.address_tag   = tag
            cache_line.written       = False
            # -- read data from local cache
            self._read_data()
            # -- done command
            self.tracker.private_accesses_i = 0                                                     # > !(private access)
             # <!> DEBUG <!>
            return tag_hit                                                                          # miss
        elif (cache_line.currentState == LineState.SHARED or cache_line.currentState == LineState.MODIFIED) and (tag_hit==True):
            # -- read data from local cache
            self._read_data()
            # -- set new tag at address
            cache_line.address_tag = tag
            # > private access
            self.tracker.private_accesses_i = 1
            return tag_hit                                                                          # hit
        else :                                                                                      # invalid state 
            raise ValueError('Invalid state: {}; at cache line: {}'.format(cache_line.currentState,line_id))

    
    def write(self, address:int):
        """Write command given to cache

        Args:
            address (int): current address to read

        Raises:
            ValueError: if a wrong state is identified

        Returns:
            bool: True for hit, False otherwise
        """
        
        # -- probe cache to match tag and check state
        tag, line_id, offset = self._probe_cache(address=address)                                   # -- probe cache
        cache_line = self.lines[line_id]                                                            # get cache line from address
        # -- check if tag hit
        tag_hit = tag==cache_line.address_tag                                                       # do tags match
        # -- check if it's a replacement writeback
        if(tag!=cache_line.address_tag and cache_line.currentState==LineState.MODIFIED):
            self.tracker.replacement_writebacks_i = 1

        if (cache_line.currentState==LineState.INVALID) or (tag_hit==False):                        # INVALID state or tag missmatch
            # -- message direcotry to invalidate copies
            self._invalidate_copies(address=address, cache_line=cache_line)
            # -- probe local to change state
            self._probe_cache(address=address)
            cache_line.currentState = LineState.MODIFIED
            cache_line.address_tag   = tag
            cache_line.written       = True
            # -- write data to local cache
            self._write_to_local()
            # > not private access
            self.tracker.private_accesses_i = 0
            return False                                                                            # miss
        elif (cache_line.currentState==LineState.SHARED):                                           # SHARED state
            # -- message direcotry to invalidate copies 
            self._invalidate_copies(address=address, cache_line=cache_line)
            # -- probe local to change state
            self._probe_cache(address=address)
            cache_line.currentState = LineState.MODIFIED
            cache_line.address_tag   = tag
            cache_line.written       = True
            # -- write data to local cache
            self._write_to_local()
            # > not private access
            self.tracker.private_accesses_i = 0
            return False                                                                            # miss
        elif(cache_line.currentState==LineState.MODIFIED) and (tag_hit==True):                      # MODIFIED state and tag match
            # -- write data to local cache
            self._write_to_local()
            # > not private access
            self.tracker.private_accesses_i = 1
            return True                                                                             # hit
        else:                                                                                       # invalid stats
            raise ValueError('Invalid state: {}; at cache line: {}'.format(cache_line.currentState,line_id))
    

    def propagate_read_miss(self, address:int):
        tag, line_id, offset = extraxct_from_address(address=address,
                            cache_lines=self.cache_lines,cache_line_size=self.cache_line_size)
        cache_line = self.lines[line_id]                                                            # cache line from address            
        if (cache_line.currentState==LineState.SHARED or cache_line.currentState==LineState.MODIFIED) and (tag==cache_line.address_tag):
            # > coherence writeback
            if (cache_line.currentState==LineState.MODIFIED):
                self.tracker.coherence_writebacks_i = 1
            # -- line is now shared
            cache_line.currentState = LineState.SHARED                                              # update cache line


    def propagate_write_miss(self, address:int):
        tag, line_id, offset = extraxct_from_address(address=address,
                            cache_lines=self.cache_lines,cache_line_size=self.cache_line_size)
        cache_line = self.lines[line_id]                                                            # cache line from address            
        if ((cache_line.currentState==LineState.SHARED or cache_line.currentState==LineState.MODIFIED) and tag==cache_line.address_tag):
            cache_line.currentState = LineState.INVALID
            
 
    def write_forward_line_single(self, address:int, hops:int):
        """Directory sends message to FURTHEST SHARER to invalidate and forward the line
        Used when it's the only sharer

        Args:
            address (int): current address
            hops (int): hpw many hops to perform
        """ 
        # -- probe local cache to match tag and check state
        self._probe_cache(address=address)
        # -- access cache to forward
        self._read_data()
        # -- send inavlidation aknowlegement & data
        self._send_data(hops=hops)


    def write_forward_line_multi(self, address:int, hops:int):
        """Directory sends message to FURTHEST SHARER to invalidate and forward the line
        Used when multiple sharers

        Args:
            address (int): current address
            hops (int): hpw many hops to perform
        """ 
        # -- probe local cache to match tag and check state
        self._probe_cache(address=address)
        # -- send inavlidation aknowlegement & data
        self._send_data(hops=hops)


    def check_match(self, address:int):
        """Check if given adress matches
        Must be in state MODIFIED or SHARED to match
        Args:
            address (int): address to check
        Returns:
            match (bool): True for match, False otehrwise
        """
        tag, line_id, offset  = extraxct_from_address( address=address,
                                cache_lines=self.cache_lines,cache_line_size=self.cache_line_size)
        cache_line = self.lines[line_id]                                                            # cache line from address
        match = (cache_line.address_tag==tag) and (cache_line.currentState==LineState.MODIFIED or cache_line.currentState==LineState.SHARED)
        return match


    def read_forward_line(self,address:int, hops:int):
        """Simulated forwarding the line on read command in a different cache

        Args:
            address (int): address of current command
        """
        self._probe_cache(address=address)
        self._read_data()
        self._send_data(hops=hops)


    def _invalidate_copies(self, address: int, cache_line: CacheLine):
        """Send message to directory to invalidate other copies
        5 cycles
        Args:
            address (int): current address
            cache_line (CacheLine): current cacahe line
        """
        self.tracker.add_total_latency(latency=5)                                                   # add latency
        self.memory_controller.write_miss(cache_id=self.id, address=address,                        # hop to directory
                                            state=cache_line.currentState)                             
    

    def _write_to_local(self):
        """Simulates Writing data to loacl cache
        1 cycle
        """
        self.tracker.add_total_latency(latency=1)                                                   # add latency



    def _read_request_data(self, cache_line: CacheLine, address: int):
        """Request read data from direcotry
        5 cycles
        Args:
            cache_line (CacheLine): cacheline of address
        """
        self.tracker.add_total_latency(latency=5)                                                   # add latency
        self.memory_controller.read_miss(cache_id=self.id, address=address)                         # hop to directory


    def _read_data(self):
        """Read data from local cache
        1 cycle
        """
        self.tracker.add_total_latency(latency=1)                                                   # add latencys

    def _probe_cache(self,address: int):
        """Probing local cache to match tag and check state
        1 cycle
        """
        self.tracker.add_total_latency(latency=1)                                                   # add latency
        tag, line_id, offset  = extraxct_from_address( address=address,                             # cache probe 
                                cache_lines=self.cache_lines,cache_line_size=self.cache_line_size)
        return tag, line_id, offset
    
    def _send_data(self, hops:int):
        """Simulates & counts time for sending data to cache asking
        3*hops cycles
        Args:
            hops (int): number of processors to hop
        """
        self.tracker.add_total_latency(latency=hops*3)                                              # add latency


