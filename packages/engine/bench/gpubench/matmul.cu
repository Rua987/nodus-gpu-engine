// A GPU workload with a checkable answer, for the contention experiment.
// Tiled single-precision matrix product, repeated; 16 entries are re-computed
// on the CPU in double precision and compared. Prints the GPU time it took.
//
//   nvcc -O2 -o matmul matmul.cu && ./matmul 4096 40
#include <cmath>
#include <cstdio>
#include <cstdlib>
#include <chrono>
#include <vector>
#include <cuda_runtime.h>

#define TILE 16

__global__ void sgemm(const float* A, const float* B, float* C, int n) {
    __shared__ float As[TILE][TILE];
    __shared__ float Bs[TILE][TILE];
    int row = blockIdx.y * TILE + threadIdx.y;
    int col = blockIdx.x * TILE + threadIdx.x;
    float acc = 0.0f;
    for (int t = 0; t < n; t += TILE) {
        As[threadIdx.y][threadIdx.x] = A[row * n + t + threadIdx.x];
        Bs[threadIdx.y][threadIdx.x] = B[(t + threadIdx.y) * n + col];
        __syncthreads();
        for (int k = 0; k < TILE; ++k) acc += As[threadIdx.y][k] * Bs[k][threadIdx.x];
        __syncthreads();
    }
    C[row * n + col] = acc;
}

static int check(cudaError_t e, const char* what) {
    if (e != cudaSuccess) {
        fprintf(stderr, "matmul: %s: %s\n", what, cudaGetErrorString(e));
        return 1;
    }
    return 0;
}

int main(int argc, char** argv) {
    int n = argc > 1 ? atoi(argv[1]) : 4096;
    int reps = argc > 2 ? atoi(argv[2]) : 40;
    if (n <= 0 || n % TILE != 0 || reps <= 0) {
        fprintf(stderr, "matmul: n must be a positive multiple of %d\n", TILE);
        return 2;
    }
    size_t count = (size_t)n * n;
    std::vector<float> A(count), B(count), C(count);
    for (size_t i = 0; i < count; ++i) {
        A[i] = (float)((i * 7) % 13) / 13.0f;
        B[i] = (float)((i * 11) % 17) / 17.0f;
    }
    float *dA = nullptr, *dB = nullptr, *dC = nullptr;
    if (check(cudaMalloc(&dA, count * sizeof(float)), "malloc A") ||
        check(cudaMalloc(&dB, count * sizeof(float)), "malloc B") ||
        check(cudaMalloc(&dC, count * sizeof(float)), "malloc C") ||
        check(cudaMemcpy(dA, A.data(), count * sizeof(float), cudaMemcpyHostToDevice), "copy A") ||
        check(cudaMemcpy(dB, B.data(), count * sizeof(float), cudaMemcpyHostToDevice), "copy B"))
        return 2;
    dim3 block(TILE, TILE), grid(n / TILE, n / TILE);
    sgemm<<<grid, block>>>(dA, dB, dC, n);                       // warm-up
    if (check(cudaGetLastError(), "launch") || check(cudaDeviceSynchronize(), "sync"))
        return 2;
    auto t0 = std::chrono::steady_clock::now();
    for (int r = 0; r < reps; ++r) sgemm<<<grid, block>>>(dA, dB, dC, n);
    if (check(cudaDeviceSynchronize(), "sync"))
        return 2;
    double secs = std::chrono::duration<double>(std::chrono::steady_clock::now() - t0).count();
    if (check(cudaMemcpy(C.data(), dC, count * sizeof(float), cudaMemcpyDeviceToHost), "copy C"))
        return 2;
    int bad = 0;
    for (int s = 0; s < 16; ++s) {
        int i = (s * 977) % n, j = (s * 613) % n;
        double ref = 0.0;
        for (int k = 0; k < n; ++k) ref += (double)A[(size_t)i * n + k] * B[(size_t)k * n + j];
        if (fabs(C[(size_t)i * n + j] - ref) > 1e-3 * fabs(ref) + 1e-2) ++bad;
    }
    double gflops = 2.0 * n * (double)n * n * reps / secs / 1e9;
    printf("matmul n=%d reps=%d gpu_seconds=%.3f gflops=%.1f bad=%d\n", n, reps, secs, gflops, bad);
    cudaFree(dA); cudaFree(dB); cudaFree(dC);
    return bad ? 1 : 0;
}
