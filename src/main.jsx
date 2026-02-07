import React, { useRef, useState, useEffect } from 'react';
import ReactDOM from 'react-dom/client';
import { Canvas, useFrame } from '@react-three/fiber';
import { PerspectiveCamera, Text, Float, MeshDistortMaterial } from '@react-three/drei';
import * as THREE from 'three';
import { Hands } from '@mediapipe/hands';
import * as cam from '@mediapipe/camera_utils';

// --- 视觉样式配置 ---
const THEME = {
  purple: "#2a0a4d",
  gold: "#d4af37",
  dark: "#050208"
};

const Card = ({ index, gameState, handPos, type }) => {
  const mesh = useRef();
  
  useFrame((state) => {
    if (!mesh.current) return;
    const t = state.clock.getElapsedTime();

    // 1. 初始状态：堆叠
    if (gameState === 'STACK') {
      mesh.current.position.lerp(new THREE.Vector3(0, index * 0.02, 0), 0.1);
      mesh.current.rotation.set(-Math.PI / 2, 0, 0);
    } 
    // 2. 洗牌状态：跟随手势散开
    else if (gameState === 'SHUFFLE') {
      const targetX = (index % 5 - 2) * 1.5 + handPos.x * 3;
      const targetY = (Math.floor(index / 5) - 2) * 1.5 + handPos.y * 3;
      mesh.current.position.lerp(new THREE.Vector3(targetX, targetY, -1), 0.05);
      mesh.current.rotation.z = Math.sin(t + index) * 0.2;
    }
    // 3. 抽牌状态：第一张牌放大
    else if (gameState === 'DRAW' && index === 0) {
      mesh.current.position.lerp(new THREE.Vector3(0, 0, 2), 0.1);
      mesh.current.rotation.y = Math.PI; // 翻转显示正面
    }
  });

  return (
    <mesh ref={mesh}>
      <boxGeometry args={[1, 1.5, 0.02]} />
      <meshStandardMaterial color={THEME.purple} metalness={0.8} roughness={0.2} />
      <Text position={[0, 0, -0.02]} rotation={[0, Math.PI, 0]} fontSize={0.12} color={THEME.gold}>
        {type}
      </Text>
    </mesh>
  );
};

function App() {
  const [gameState, setGameState] = useState('STACK');
  const [handPos, setHandPos] = useState({ x: 0, y: 0 });
  const videoRef = useRef(null);
  const venues = ["古堡", "田园", "现代", "屋顶", "教堂", "野外", "小清新", "校园"];

  useEffect(() => {
    const hands = new Hands({
      locateFile: (file) => `https://cdn.jsdelivr.net/npm/@mediapipe/hands/${file}`,
    });
    hands.setOptions({ maxNumHands: 1, modelComplexity: 1 });
    hands.onResults((res) => {
      if (res.multiHandLandmarks?.length > 0) {
        const lm = res.multiHandLandmarks[0];
        setHandPos({ x: (lm[9].x - 0.5) * 2, y: -(lm[9].y - 0.5) * 2 });
        
        // 简单逻辑：手部高度决定状态
        if (lm[9].y > 0.7) setGameState('STACK');
        else if (lm[9].y < 0.3) setGameState('DRAW');
        else setGameState('SHUFFLE');
      }
    });

    const camera = new cam.Camera(videoRef.current, {
      onFrame: async () => { await hands.send({ image: videoRef.current }); },
      width: 320, height: 240
    });
    camera.start();
  }, []);

  return (
    <>
      <video ref={videoRef} style={{ position: 'absolute', right: 20, top: 20, width: 240, border: `1px solid ${THEME.gold}`, zIndex: 10, transform: 'scaleX(-1)' }} />
      <Canvas>
        <PerspectiveCamera makeDefault position={[0, 0, 5]} />
        <pointLight position={[10, 10, 10]} intensity={1.5} color={THEME.gold} />
        <ambientLight intensity={0.5} />
        
        {Array.from({ length: 15 }).map((_, i) => (
          <Card key={i} index={i} gameState={gameState} handPos={handPos} type={venues[i % venues.length]} />
        ))}

        <Float speed={2} rotationIntensity={0.5}>
          <mesh scale={10} position={[0,0,-5]}>
            <sphereGeometry />
            <MeshDistortMaterial color="#100220" speed={2} distort={0.3} />
          </mesh>
        </Float>
      </Canvas>
    </>
  );
}

ReactDOM.createRoot(document.getElementById('root')).render(<App />);
