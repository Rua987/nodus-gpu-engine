// Induced GPU load for the contention experiment (docs/COMPUTE_GPU.md).
// Keeps every SM busy with dependent FMAs for N seconds, then exits on its own.
// Built on the VM with nvcc; the run that uses it says so in its report.
//
//   nvcc -O2 -o nge_burn gpu_burn.cu && ./nge_burn 180
#include <cstdio>
#include <cstdlib>
#include <chrono>
#include <cuda_runtime.h>

__global__ void burn(float* out, int iters) {
    float a = threadIdx.x * 1e-3f;
    float b = blockIdx.x * 1e-3f;
    for (int i = 0; i < iters; ++i) {
        a = fmaf(a, 1.000001f, b);
        b = fmaf(b, 0.999999f, a);
    }
    out[blockIdx.x * blockDim.x + threadIdx.x] = a + b;   // keep the work alive
}

int main(int argc, char** argv) {
    double seconds = argc > 1 ? atof(argv[1]) : 60.0;
    int sms = 0;
    if (cudaDeviceGetAttribute(&sms, cudaDevAttrMultiProcessorCount, 0) != cudaSuccess || sms <= 0) {
        fprintf(stderr, "nge_burn: no CUDA device\n");
        return 2;
    }
    const int threads = 256;
    const int blocks = sms * 8;
    float* out = nullptr;
    if (cudaMalloc(&out, sizeof(float) * blocks * threads) != cudaSuccess) {
        fprintf(stderr, "nge_burn: cudaMalloc failed\n");
        return 2;
    }
    printf("nge_burn: %d SMs, %d blocks x %d threads, %.0f s\n", sms, blocks, threads, seconds);
    fflush(stdout);
    auto t0 = std::chrono::steady_clock::now();
    long launches = 0;
    for (;;) {
        burn<<<blocks, threads>>>(out, 1 << 16);
        cudaError_t e = cudaDeviceSynchronize();
        if (e != cudaSuccess) {
            fprintf(stderr, "nge_burn: %s\n", cudaGetErrorString(e));
            return 2;
        }
        ++launches;
        double el = std::chrono::duration<double>(std::chrono::steady_clock::now() - t0).count();
        if (el >= seconds) break;
    }
    printf("nge_burn: done, %ld launches\n", launches);
    cudaFree(out);
    return 0;
}
