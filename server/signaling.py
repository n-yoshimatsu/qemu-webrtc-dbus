"""
WebRTC Signaling Server

SDP offer/answerとICE candidateの交換を処理
"""

import json
import logging
from aiohttp import web
from aiortc import RTCPeerConnection, RTCSessionDescription
from aiortc.contrib.media import MediaBlackhole

from .video_track import QEMUVideoTrack

logger = logging.getLogger(__name__)


class SignalingServer:
    """WebRTCシグナリングサーバー"""
    
    def __init__(self, display_capture):
        """
        Args:
            display_capture: DisplayCaptureインスタンス
        """
        self.display_capture = display_capture
        self.pcs = set()  # アクティブなRTCPeerConnection
        
        logger.info("SignalingServer initialized")
    
    async def handle_offer(self, request: web.Request) -> web.Response:
        """
        WebRTCクライアントからのOfferを処理
        
        Args:
            request: HTTP POSTリクエスト（SDP offer含む）
        
        Returns:
            SDP answerを含むJSONレスポンス
        """
        try:
            params = await request.json()
            offer = RTCSessionDescription(
                sdp=params['sdp'],
                type=params['type']
            )
            
            logger.info(f"Received offer from {request.remote}")
            
            # RTCPeerConnection作成
            pc = RTCPeerConnection()
            self.pcs.add(pc)
            
            @pc.on("connectionstatechange")
            async def on_connectionstatechange():
                logger.info(f"Connection state: {pc.connectionState}")
                if pc.connectionState in ["failed", "closed"]:
                    await self.cleanup_pc(pc)
            
            @pc.on("iceconnectionstatechange")
            async def on_iceconnectionstatechange():
                logger.info(f"ICE connection state: {pc.iceConnectionState}")
            
            # ビデオトラック追加（10fpsで大幅なパフォーマンス改善）
            video_track = QEMUVideoTrack(self.display_capture, fps=10)
            pc.addTrack(video_track)
            
            # Offerを設定
            await pc.setRemoteDescription(offer)
            
            # Answer作成
            answer = await pc.createAnswer()
            await pc.setLocalDescription(answer)
            
            logger.info("Answer created and sent")
            
            return web.json_response({
                'sdp': pc.localDescription.sdp,
                'type': pc.localDescription.type
            })
            
        except Exception as e:
            logger.error(f"Error handling offer: {e}")
            import traceback
            logger.error(traceback.format_exc())
            return web.json_response(
                {'error': str(e)},
                status=500
            )
    
    async def cleanup_pc(self, pc: RTCPeerConnection):
        """
        RTCPeerConnectionのクリーンアップ
        
        Args:
            pc: クリーンアップするRTCPeerConnection
        """
        logger.info("Cleaning up peer connection")
        
        # トラック停止
        for sender in pc.getSenders():
            if sender.track:
                sender.track.stop()
        
        # 接続クローズ
        await pc.close()
        
        # セットから削除
        self.pcs.discard(pc)
    
    async def cleanup_all(self):
        """すべての接続をクリーンアップ"""
        logger.info(f"Cleaning up {len(self.pcs)} peer connections")
        
        # すべてのRTCPeerConnectionをクローズ
        coros = [self.cleanup_pc(pc) for pc in list(self.pcs)]
        if coros:
            import asyncio
            await asyncio.gather(*coros, return_exceptions=True)
        
        logger.info("All peer connections cleaned up")
