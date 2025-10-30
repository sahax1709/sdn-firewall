# firewall.py -- working POX firewall example
# Run: ./pox.py log.level --DEBUG firewall

from pox.core import core
import pox.openflow.libopenflow_01 as of
from pox.lib.packet import ethernet, ipv4, arp, tcp, icmp

log = core.getLogger()

FIREWALL_RULES = [
    ("block_ip", "10.0.0.5"),  # block traffic to/from 10.0.0.3
    ("block_port", 22),        # block TCP port 22
    ("block_icmp", False)      # set True to block all ping
]


class Firewall(object):
    def __init__(self, connection):
        self.connection = connection
        connection.addListeners(self)
        log.info("Firewall connected to %s", connection)

    def _install_flow(self, match, actions, idle_timeout=60, hard_timeout=0):
        fm = of.ofp_flow_mod()
        fm.match = match
        fm.idle_timeout = idle_timeout
        fm.hard_timeout = hard_timeout
        fm.actions = actions
        self.connection.send(fm)

    def _packet_matches_block(self, packet):
        # Ignore IPv6
        if packet.type == ethernet.IPV6_TYPE:
            return False

        ip = packet.find('ipv4')
        if not ip:
            return False  # not IP (like ARP)

        for rtype, rval in FIREWALL_RULES:
            if rtype == "block_ip":
                if str(ip.srcip) == rval or str(ip.dstip) == rval:
                    log.debug("BLOCK match: block_ip %s", rval)
                    return True
            if rtype == "block_icmp" and rval:
                if ip.protocol == ipv4.ICMP_PROTOCOL:
                    log.debug("BLOCK match: block_icmp")
                    return True
            if rtype == "block_port":
                if ip.protocol == ipv4.TCP_PROTOCOL:
                    tcp_seg = packet.find('tcp')
                    if tcp_seg and (tcp_seg.srcport == rval or tcp_seg.dstport == rval):
                        log.debug("BLOCK match: block_port %s", rval)
                        return True
        return False

    def _handle_PacketIn(self, event):
        packet = event.parsed
        if not packet.parsed:
            return

        match = of.ofp_match.from_packet(packet)

        # ✅ Always allow ARP so hosts can resolve each other
        if packet.type == ethernet.ARP_TYPE:
            msg = of.ofp_packet_out()
            msg.data = event.ofp
            msg.actions.append(of.ofp_action_output(port=of.OFPP_FLOOD))
            msg.in_port = event.port
            self.connection.send(msg)
            log.debug("Flooding ARP packet")
            return

        # Apply firewall rules only for IPv4 packets
        if self._packet_matches_block(packet):
            # Drop: install a drop flow
            fm = of.ofp_flow_mod()
            fm.match = match
            fm.idle_timeout = 300
            fm.hard_timeout = 0
            # No actions = drop
            self.connection.send(fm)
            log.info("DROP: %s", match)
            return

        # Allow everything else
        actions = [of.ofp_action_output(port=of.OFPP_FLOOD)]
        self._install_flow(match, actions)
        msg = of.ofp_packet_out(data=event.ofp, in_port=event.port, actions=actions)
        self.connection.send(msg)
        log.debug("ALLOW: %s", match)


def launch():
    def start_switch(event):
        Firewall(event.connection)
    core.openflow.addListenerByName("ConnectionUp", start_switch)
    log.info("POX Firewall started with rules: %s", FIREWALL_RULES)

