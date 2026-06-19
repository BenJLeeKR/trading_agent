import os
import glob

def main():
    log_dir = "/workspace/agent_trading/logs"
    log_files = glob.glob(os.path.join(log_dir, "*.log"))
    
    # Sort files by modification time (newest first)
    log_files.sort(key=os.path.getmtime, reverse=True)
    
    universe_lines = []
    
    # Check the newest files first
    for file in log_files:
        try:
            with open(file, 'r') as f:
                lines = f.readlines()
                for line in lines:
                    if "Trading universe (" in line:
                        universe_lines.append((file, line.strip()))
        except Exception:
            pass
            
        if len(universe_lines) > 0:
            # Found in the most recent relevant file
            break

    if not universe_lines:
        print("최근 로그에서 유니버스 선정 내역을 찾을 수 없습니다.")
        return

    print("=== 가장 최근 선정된 유니버스 종목 내역 ===")
    for file, line in universe_lines:
        print(f"[{os.path.basename(file)}]")
        print(line)

if __name__ == '__main__':
    main()
