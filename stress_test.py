import time
import multiprocessing
import os

def cpu_stress():
    """CPU를 100% 사용하는 무한 루프 함수"""
    print(f"🔥 CPU Stress Process Started: PID {os.getpid()}")
    while True:
        _ = 123456789 * 987654321

if __name__ == "__main__":
    print("========================================")
    print("🚀 CPU 부하 테스트 스크립트 시작")
    print("========================================")
    print(f"코어 수: {multiprocessing.cpu_count()}")
    print("모든 코어에 부하를 줍니다... (종료하려면 Ctrl+C)")
    
    processes = []
    try:
        # CPU 코어 수만큼 프로세스 생성하여 부하 발생
        for _ in range(multiprocessing.cpu_count()):
            p = multiprocessing.Process(target=cpu_stress)
            p.start()
            processes.append(p)
            
        # 메인 프로세스 대기
        for p in processes:
            p.join()
            
    except KeyboardInterrupt:
        print("\n🛑 테스트 중지 중...")
        for p in processes:
            p.terminate()
        print("✅ 종료 완료")
